#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import torch
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D, proj3d

import json
from typing import List, Optional, Union

import torch.multiprocessing as mp
from torch.multiprocessing import Queue

from lib.learn_nn_ds import NL_DS
from lib.learn_ply_ds import PLY_DS
from lib.utils.utils import time_stamp
from lib.utils.log_config import logger
from lib.utils.plot_tools import plot_ds_2Dstream, plot_trajectory, plot_contours
from lib.utils.data_loader import load_hdf5_data
from lib.utils.waypoint_utils import scatter_waypoints, normalize_waypoints, augment_data, plot_rollouts, clean_waypoints

from sim.playback_robomimic import playback_dataset

import h5py

def waypoint_policy(learner_type: str,
                    waypoint_positions: np.ndarray,
                    waypoint_velocities: np.ndarray,
                    n_epochs: int,
                    plot: Optional[bool] = False,
                    model_name: Optional[str] = 'waypoint-test',
                    save_dir: str = 'res/',
                    device: str = 'cuda:0' if torch.cuda.is_available() else 'cpu',
                    subgoal: Optional[int] = None,
                    augment_rate: Optional[int] = None,
                    augment_alpha: Optional[float] = None,
                    augment_distribution: Optional[str] = 'normal',
                    normalize_magnitude: Optional[float] = None,
                    clean: Optional[bool] = False) :

    """ Train a stable/unstable policy to learn a nonlinear dynamical system. """

    name = f'{model_name}-{learner_type}-subgoal{subgoal}-{time_stamp()}'
    goal = waypoint_positions[-1].reshape(1, waypoint_positions.shape[1])

    # set goal velocity to zero
    waypoint_velocities[-1] = np.zeros(waypoint_velocities[-1].shape)
    logger.info(f'Subgoal position: {goal}')
    # Maybe normalize the data
    if normalize_magnitude is not None:
        waypoint_velocities = normalize_waypoints(waypoint_velocities, normalize_magnitude)
    
    # Plot the waypoints
    scatter_waypoints(waypoint_positions, waypoint_velocities, title=f'Subgoal {subgoal} Waypoints')
    
    # Maybe clean the data 
    if clean:
        waypoint_positions, waypoint_velocities = clean_waypoints(waypoint_positions, waypoint_velocities)
        scatter_waypoints(waypoint_positions, waypoint_velocities, title=f'Subgoal {subgoal} Cleaned Waypoints')
    
    # Maybe augment the data
    if augment_rate is not None and augment_alpha is not None:   
        logger.info(f'Augmenting data with rate {augment_rate} and alpha {augment_alpha} according to a {augment_distribution} distribution.')
        waypoint_positions, waypoint_velocities = augment_data(waypoint_positions, waypoint_velocities, augment_alpha, augment_rate, augment_distribution)
        scatter_waypoints(waypoint_positions, waypoint_velocities, title=f'Subgoal {subgoal} Augmented Waypoints')

    if learner_type in ["snds", "nn", "sdsef", "lnet"]: 
        model = NL_DS(network=learner_type, data_dim=waypoint_positions.shape[1], goal=goal, device=device,
                      eps=0.2, alpha=0.1)
        model.fit(waypoint_positions, waypoint_velocities, n_epochs=n_epochs, lr_initial=1e-4)
    else:
        raise NotImplementedError(f'Learner type {learner_type} not available!')

    if plot:
        plot_ds_2Dstream(model, waypoint_positions, save_dir=save_dir, file_name=f'{name}-ds', show_rollouts=True)

        if model.lpf(waypoint_positions[-1].reshape(1, waypoint_positions.shape[1])) is not None:
            plot_contours(model.lpf, waypoint_positions, save_dir=save_dir, file_name=f'{name}-lpf')

    model.save(model_name=name, dir=save_dir)
    #torch.save(model, os.path.join(save_dir, name+".pt"))
    print(f'Model saved as {name} in {save_dir}.')
    return model

def train_policy_for_subgoal(subgoal_data, config, subgoal_index):
    waypoint_position = subgoal_data["waypoint_position"]
    waypoint_velocity = subgoal_data["waypoint_velocity"]
    print(f"Subgoal {subgoal_index} waypoint positions: {waypoint_position}")
    print(f"Subgoal {subgoal_index} waypoint velocities: {waypoint_velocity}")
    ds_policy = waypoint_policy(
        config['learner_type'],
        waypoint_positions=waypoint_position,
        waypoint_velocities=waypoint_velocity,
        n_epochs=config['num_epochs'],
        device=config['device'],
        subgoal=subgoal_index,
        augment_rate=config['augment_rate'],
        augment_alpha=config['augment_alpha'],
        augment_distribution=config['augment_distribution'],
        normalize_magnitude=config['normalize_magnitude'],
        clean=config['clean'],
    )

    print(f"Subgoal {subgoal_index} training complete.")

def main(config_path):
    with open(config_path, 'r') as file:
        config = json.load(file)

    demos = config['demos']
    data = {}
    demo = demos[0]

    if config['seed'] is not None:
        print(f"Setting seed to {config['seed']}")
        seed = config['seed']
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        else:
            torch.manual_seed(seed)
    
    # get number of subgoals in the demo
    with h5py.File(config['data_dir'], 'r') as f: 
        #print(f"data/demo_{demo}/{config['subgoals_dataset']}")
        subgoals = f[f"data/demo_{demo}/{config['subgoals_dataset']}"]
        num_subgoals = len(subgoals)

    for i in range(num_subgoals):
        waypoint_position, waypoint_velocity, waypoint_orientation, waypoint_gripper_action = load_hdf5_data(
            dataset=config['data_dir'],
            demo_id=demo,
            waypoints_dataset_name=config['waypoints_dataset'],
            subgoals_dataset_name=config['subgoals_dataset'],
            subgoal=i
        )
        data["subgoal_" + str(i)] = {"waypoint_position": waypoint_position, "waypoint_velocity": waypoint_velocity, "waypoint_orientation": waypoint_orientation, "waypoint_gripper_action": waypoint_gripper_action}

    print(f'Data loaded from {config["data_dir"]}.')
    if config['model_names'] is None or config['model_dir'] is None:
        # Use multiprocessing to train a policy for each subgoal
        mp.set_start_method('spawn')  # Must be 'spawn' to avoid issues with CUDA
        
        ps = []

        # Create and start processes
        for i in range(len(data.keys())):
            p = mp.Process(
                target=train_policy_for_subgoal, 
                args=(data["subgoal_" + str(i)], config, i),
                name=f"{i}")
            p.start()
            ps.append(p)

        # Wait for all processes to finish 
        for p in ps:
            p.join(timeout=120)  # Add a timeout to avoid indefinite hanging
        
        return
    else:
        policies = []
        for i, model_name in enumerate(config['model_names']):
            print(f"Loading model {model_name}")
            waypoint_positions = data["subgoal_"+str(i)]["waypoint_position"]
            model = NL_DS(network=config['learner_type'], data_dim=waypoint_position.shape[1], goal=waypoint_position[-1].reshape(1, waypoint_positions.shape[1]), device=config['device'],
                eps=0.2, alpha=0.1)
            # Load the model
            model.load(model_name=model_name, dir=config["model_dir"])
            policies.append(model)
    
    # maybe plot the rollouts 
    if config['plot']:
        plot_rollouts(data, policies)

    # maybe playback the rollout in the simulation
    if config['playback']:
        print("Starting playback...")
        playback_dataset(
            dataset_path=config['data_dir'],
            video_path=config['video_path'],
            camera_names=config['camera_names'],
            video_skip=config['video_skip'],
            policies=policies,
            subgoals=[{"subgoal_pos": subgoal_data["waypoint_position"][-1],
                       "subgoal_ori": subgoal_data["waypoint_orientation"][-1],
                       "subgoal_gripper": subgoal_data["waypoint_gripper_action"][-1]} for subgoal_data in data.values()],
            multiplier=config['multiplier'], 
            force_dim=config['force_dim'],
            force_time_step=config['force_time_step']
        )
    print("Process complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Nonlinear DS experiments CLI interface.')
    parser.add_argument('--config', type=str, required=True, help='Path to the JSON config file.')
    args = parser.parse_args()

    main(args.config)