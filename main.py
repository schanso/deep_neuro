#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Dec  1 15:01:26 2017

@author: jannes
"""

###########
# IMPORTS #
###########

import datetime

from sklearn.model_selection import train_test_split
import tensorflow as tf
import pandas as pd
import numpy as np

import lib.io as io
import lib.cnn as cnn
import lib.helpers as hlp

sess_no = '141023'
decode_for = 'resp'

file = '/home/jannes/dat/results/accuracy/141023/combinations/resp.txt'
# Get current params from file
with open(file, 'rb') as f:
    params = np.loadtxt(f, dtype='object', delimiter='\n')
params = params.tolist()
curr_params = eval(params.pop())
params = np.array(params)
with open(file, 'wb') as f:
    np.savetxt(f, params, fmt='%s')

str_to_print = curr_params[2]


##########
# PARAMS #
##########
        
# global params
sess_no = sess_no
interval = curr_params[1]  # 'sample_500'
target_areas = curr_params[0]
decode_for = decode_for  # 'resp' for behav resp, 'stim' for stimulus class
elec_type = 'grid' # any one of single|grid|average
only_correct_trials = False  # if pre-sample, only look at correct trials

# hyper params
n_iterations = 100
size_of_batches = 100
dist = 'random_normal'
batch_norm = 'after'
nonlin = 'leaky_relu'
normalized_weights = True
learning_rate = 1e-5
l2_regularization_penalty = 20
keep_prob_train = .1

# layer dimensions
n_layers = 6
patch_dim = [1, 5]
pool_dim = [1, 2]
in1, out1 = [1, 3]
in2, out2 = [3, 6]
in3, out3 = [6, 12]
in4, out4 = [12, 36]
in5, out5 = [36, 72]
in6, out6 = [72, 288]
in7, out7 = [288, 512]
in8, out8 = [512, 1024]
fc_units = 200
channels_in = [in1, in2, in3, in4, in5, in6, in7, in8][:n_layers]
channels_out = [out1, out2, out3, out4, out5, out6, out7, out8][:n_layers]


#########
# PATHS #
#########

data_path = '/media/jannes/disk2/pre-processed/' + interval + '/'
raw_path = '/media/jannes/disk2/raw/' + sess_no + '/session01/'
file_name = sess_no + '_freq1000low5hi450order3.npy'
file_path = data_path + file_name
rinfo_path = raw_path + 'recording_info.mat'
tinfo_path = raw_path + 'trial_info.mat'

seed = np.random.randint(1,10000)
run_counter = 0
for count, target_area in enumerate(target_areas):
    print(str_to_print)

    ########
    # DATA #
    ########
    
    # Auto-define number of classes
    classes = 2 if decode_for == 'resp' else 5
    
    # Load data and targets
    data, n_chans = io.get_subset(file_path, target_area, raw_path, 
                                  elec_type, return_nchans=True, 
                                  only_correct_trials=only_correct_trials)
    targets = io.get_targets(decode_for, raw_path, elec_type, n_chans,
                             only_correct_trials=only_correct_trials)
    
    # train/test params
    samples_per_trial = data.shape[2]
    n_chans = data.shape[1]
    train_size = .8
    test_size = .2
    
    # split into train and test
    indices = np.arange(data.shape[0])
    train, test, train_labels, test_labels, idx_train, idx_test = (
            train_test_split(
                data, 
                targets, 
                indices,
                test_size=test_size, 
                random_state=seed)
            )
    
    # Subsetting to get equal class proportions in the traning + test data.
    # We want the same subset of test observations for all areas in
    # target_areas, thus we only assing indices on the first iteration.
    ind_train = hlp.subset_train(train_labels, classes, size_of_batches)
    if count == 0:
        ind_test = hlp.subset_test(test_labels, classes)
        run_counter += 1
    
    
    ##########
    # LAYERS #
    ##########
    
    # placeholders
    x = tf.placeholder(tf.float32, shape=[
            None, n_chans, samples_per_trial
            ])
    y_ = tf.placeholder(tf.float32, shape=[None, classes])
    training = tf.placeholder_with_default(True, shape=())
    keep_prob = tf.placeholder(tf.float32)
    
    # Network
    out, weights = cnn.create_network(
            n_layers=n_layers, 
            x_in=x, 
            n_in=channels_in, 
            n_out=channels_out, 
            patch_dim=patch_dim,
            pool_dim=pool_dim,
            training=training, 
            n_chans=n_chans,
            n_samples=samples_per_trial,
            weights_dist=dist, 
            normalized_weights=normalized_weights,
            nonlin=nonlin,
            bn=True)
    
    
    ###################
    # FULLY-CONNECTED #
    ###################
    
    # Fully-connected layer (BN)
    fc1, weights[n_layers] = cnn.fully_connected(out, 
                bn=True, 
                units=fc_units, 
                nonlin=nonlin,
                weights_dist=dist,
                normalized_weights=normalized_weights)
    
    
    ###################
    # DROPOUT/READOUT #
    ###################
    
    # Dropout (BN)
    fc1_drop = tf.nn.dropout(fc1, keep_prob)
    
    # Readout
    weights[n_layers+1] = cnn.init_weights([fc_units, classes])
    y_conv = tf.matmul(fc1_drop, weights[n_layers+1])
    softmax_probs = tf.contrib.layers.softmax(y_conv)
    weights_shape = [tf.shape(el) for el in weights.values()]
    
    #############
    # OPTIMIZER #
    #############
    
    # Loss
    loss = cnn.l2_loss(weights, 
                       l2_regularization_penalty, 
                       y_, 
                       y_conv, 
                       'loss')
    
    # Optimizer
    train_step = tf.train.AdamOptimizer(learning_rate).minimize(loss)
    correct_prediction = tf.equal(tf.argmax(y_conv, 1), tf.argmax(y_, 1))
    accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))
    
    
    ######################
    # SOFTMAX REGRESSION #
    ######################
    
    # Implement softmax regression for comparison
    x_reg = tf.placeholder(tf.float32, shape=[None, 
                                              n_chans * samples_per_trial])
    y_reg = tf.placeholder(tf.float32, shape=[None, classes])
    y_hat_reg = cnn.softmax_regression(x_reg, classes)
    cross_entropy = tf.reduce_mean(-tf.reduce_sum(y_reg * tf.log(y_hat_reg),
                                                  reduction_indices=[1]))
    train_step_reg = tf.train.AdamOptimizer(learning_rate).minimize(
            cross_entropy)
    correct_prediction_reg = tf.equal(tf.argmax(y_hat_reg, 1), 
                                      tf.argmax(y_reg, 1))
    accuracy_reg = tf.reduce_mean(tf.cast(correct_prediction_reg, tf.float32))
    
    
    ############
    # TRAINING #
    ############
    
    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())
        
        # Number of batches to train on
        for i in range(n_iterations):            
            # Every n iterations, print training accuracy
            if i % 10 == 0:
                train_accuracy = accuracy.eval(feed_dict={
                        x: train[ind_train,:,:],
                        y_: train_labels[ind_train,:],
                        keep_prob: 1.0
                        })
                print('step %d, training accuracy: %g' % (
                        i, train_accuracy))
      
            # Training
            train_step.run(feed_dict={
                    x: train[ind_train,:,:], 
                    y_: train_labels[ind_train,:],
                    keep_prob: keep_prob_train
                    })
            train_step_reg.run(feed_dict={
                    x_reg: train[ind_train,:,:].reshape(
                            len(ind_train), -1), 
                    y_reg: train_labels[ind_train,:].reshape(
                            len(ind_train), -1)
                    })
        
        # Print test accuracy
        acc = accuracy.eval(feed_dict={
                x: test[ind_test,:,:],
                y_: test_labels[ind_test,:],
                keep_prob: 1.0
                })
        acc_reg = accuracy_reg.eval(feed_dict={
                x_reg: test[ind_test,:,:].reshape(len(ind_test), -1),
                y_reg: test_labels[ind_test,:].reshape(len(ind_test), -1)
                })
        probs = softmax_probs.eval(feed_dict={
                x: test[ind_test,:,:],
                y_: test_labels[ind_test,:],
                keep_prob: 1.0
                })
        print('test accuracy: CNN %g, Regression %g' % (acc, acc_reg))
        
        # Get size of weights
        size_weights = sess.run(weights_shape)
    
    
    #################
    # DOCUMENTATION #
    #################
    
    time = str(datetime.datetime.now())
    
    # Store data in list, convert to df
    data = [acc_reg, acc, n_iterations, size_of_batches, 
            l2_regularization_penalty, learning_rate, str(patch_dim), 
            str(pool_dim), str(channels_out), fc_units, dist, batch_norm, 
            nonlin, str(target_area), normalized_weights, 
            only_correct_trials, 0, train_accuracy, keep_prob_train, 
            n_layers, time, probs, test_labels[ind_test,:], 
            idx_test[ind_test], run_counter, target_areas]
    df = pd.DataFrame([data], 
                      columns=['acc_reg', 'acc', 'iterations', 
                               'batch_size', 'l2 penalty', 
                               'learning_rate', 'patch_dim', 'pool_dim', 
                               'output_channels', 'fc_units', 'dist', 
                               'time_of_BN', 'nonlinearity', 'area','std', 
                               'only_correct_trials', 'empty', 
                               'train_accuracy', 'keep_prob', 'n_layers', 
                               'time', 'probs', 'test_labels', 
                               'test_indices', 'run_counter', 'target_areas'],
                      index=[0])
    
    # Save to file
    with open('/home/jannes/dat/results/accuracy/' + sess_no 
              + '/combinations/' + sess_no + '_acc_' + decode_for + '_' 
              + interval + '.csv', 'a') as f:
       df.to_csv(f, index=False, header=False)
