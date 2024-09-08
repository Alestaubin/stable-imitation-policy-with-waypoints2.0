"""
A collection of functions to playback the simulation with the given policies and waypoints.
"""

import h5py
import imageio
import numpy as np

import robomimic
import robomimic.utils.obs_utils as ObsUtils
import robomimic.utils.env_utils as EnvUtils
import robomimic.utils.file_utils as FileUtils
import robosuite.utils.transform_utils as TransUtils
import math
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R
from lib.utils.log_config import logger
import cv2
from lib.utils.utils import time_stamp
import os

def playback_dataset(
    dataset_path,
    video_name=None,
    camera_names=["agentview"],
    video_skip=5,
    policies=None,
    angular_policies=None,
    subgoals=None,
    initial_state=None,
):
    """
    Playback a dataset with the given policies and waypoints, while also plotting the 
    distance between the current end-effector (EE) position and the subgoal EE position.
    
    args:
        dataset_path (str): path to the hdf5 dataset
        video_name (str): path to save the video to
        render_image_names (list): list of camera names to render
        video_skip (int): Number of steps to skip between video frames
        policies (list): list of policies to use for playback
        subgoals (list): list of subgoals in the trajectory in the form [{"subgoal_pos":subgoal_pos, "subgoal_ori": subgoal_ori, "subgoal_gripper": subgoal_gripper}, ...]
        multiplier (float): scaling factor for the action space
    """
    # some arg checking
    write_video = True
    print("writing video to ", video_name)

    # Create environment
    dummy_spec = dict(
        obs=dict(
                low_dim=["robot0_eef_pos"],
                rgb=[],
            ),
    )
    ObsUtils.initialize_obs_utils_with_obs_specs(dummy_spec)

    env_meta = FileUtils.get_env_metadata_from_dataset(dataset_path)
    env_meta["env_kwargs"]["controller_configs"]["interpolation"] = "linear"
    env_meta["env_kwargs"]["controller_configs"]["control_delta"] = True # Whether to control the robot using delta or absolute commands (where absolute commands are taken in the world coordinate frame)

    env = EnvUtils.create_env_from_metadata(env_meta=env_meta, render=False, render_offscreen=write_video)
    
    # load the initial state
    env.reset()
    env.reset_to(initial_state)

    print("=======================================================================================")    
    print("ENV:",env)

    if not EnvUtils.is_robosuite_env(env_meta): 
        raise ValueError("Playback only supported for robosuite environments.")

    with h5py.File(dataset_path, "r") as f:
        pass

    # Initialize video writer
    video_writer = imageio.get_writer(video_name, fps=20)

    # Get initial state of environment
    obs = env.reset()
    
    action_num = 0
    distances = []

    for i in range(len(subgoals)):
        subgoal_pos = subgoals[i]["subgoal_pos"]
        subgoal_ee_euler = subgoals[i]["subgoal_euler"]

        while math.dist(subgoals[i]["subgoal_pos"], obs["robot0_eef_pos"]) > 0.003 and action_num < 5000:
            current_ee_pos = obs["robot0_eef_pos"]
            distance = round(math.dist(subgoal_pos, current_ee_pos), 5)
            
            sim_quat = env.env.sim.data.get_body_xquat('gripper0_eef')
            sim_quat = TransUtils.convert_quat(sim_quat)
            sim_mat = TransUtils.quat2mat(sim_quat)
            sim_euler = TransUtils.mat2euler(sim_mat)

            # reshape
            current_ee_pos = np.array(current_ee_pos).reshape(1,3)

            # Get the linear action
            action_linear = np.array(policies[i].predict(current_ee_pos))[0]

            if angular_policies is None:
                action_angular = subgoal_ee_euler - sim_euler
                #normalize if norm is too big
                if np.linalg.norm(action_angular) > 0.25:
                    print("Normalizing action_angular")
                    action_angular = action_angular / np.linalg.norm(action_angular) * 0.25
            else: 
                action_angular = angular_policies[i].predict(current_ee_pos)[0] # NOTE: let's see if this works. It does not :(

            if i == 0 :
                action_gripper = np.array([-1])  # Open the gripper for the first subgoal
            else: 
                action_gripper = np.array([0]) 

            action = np.concatenate((action_linear, action_angular, action_gripper))
            
            action = np.array(action, copy=True)

            # print feedback
            if action_num % 25 == 0:
                logger.info(f"Distance to subgoal {i}: {distance}, Action number: {action_num}, Current euler: {sim_euler}, Subgoal euler: {subgoal_ee_euler}")
            
            # Take the action in the environment
            obs, _, _, _ = env.step(action)

            # Save the frames (agentview)
            if action_num % video_skip == 0:
                video_img = []
                for cam_name in camera_names:
                    video_img.append(put_text(env.render(mode="rgb_array", height=512, width=512, camera_name=cam_name), f"Subgoal {i}, Action: {action}", font_size=0.25, thickness=1, position="bottom"))
                video_img = np.concatenate(video_img, axis=1)  # Concatenate horizontally
                video_img = put_text(video_img, f"ee_euer: {sim_euler}, ee_pos: {obs['robot0_eef_pos']}", font_size=0.25, thickness=1, position="top")
                video_writer.append_data(video_img)
        
            action_num += 1


        # Activate the gripper
        # NOTE : This is a temporary solution. There should be a check that the object has been grasped 
        action_gripper = subgoals[i]["subgoal_gripper"]
        action = np.zeros_like(action)
        action[-1] = action_gripper
        logger.info("\n####################################################\n################ Activating gripper ################\n####################################################")
        # do while loop
        while True:
            #print(f'Activating gripper: {action}, Gripper qpos: {obs["robot0_gripper_qpos"]}, Gripper qvel: {obs["robot0_gripper_qvel"]}')
            obs, _, _, _ = env.step(action)
            video_img = []
            for cam_name in camera_names:
                video_img.append(put_text(env.render(mode="rgb_array", height=512, width=512, camera_name=cam_name), f"Gripper Vel: {obs['robot0_gripper_qvel'][0]}"))
            video_img = np.concatenate(video_img, axis=1)  # Concatenate horizontally
            video_writer.append_data(video_img)
            action_num += 1

            # if the gripper vel is lower than 0.0001, it is most likely not moving 
            # and the object has been grasped
            if abs(obs["robot0_gripper_qvel"][0]) <= 0.001: 
                break

    # Clean and convert distances to a numpy array
    distances = np.array([d for d in distances if isinstance(d, (float, int))], dtype=float)

    # Close video writer
    video_writer.close()

def put_text(img, text, font_size=1, thickness=2, position="top"):
    img = img.copy()
    if position == "top":
        p = (10, 30)
    elif position == "bottom":
        p = (10, img.shape[0] - 60)
    # put the frame number in the top left corner
    img = cv2.putText(
        img,
        str(text),
        p,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_size,
        (0, 255, 255),
        thickness,
        cv2.LINE_AA,
    )
    return img
