# Learning Stable Imitation Policies with Waypoints

## Overview

Imitation learning can be leveraged to tackle complex motion planning problems by training a policy to imitate an expert's behavior. We attempt to safely imitate human demonstration from video data.

This repository builds on top of the following two publications:

* **SNDS** — A. Abyaneh, M. Sosa, H.-C. Lin. Globally stable neural imitation policies. International Conference on Robotics and Automation, 2024.

* **PLYDS** — A. Abyaneh and H.-C. Lin. Learning Lyapunov-stable polynomial dynamical systems through imitation. In 7th Annual
Conference on Robot Learning, 2023.

## Installation 
First, clone this repository on your device.
```
git clone https://github.com/Alestaubin/stable-imitation-policy-with-waypoints.git
cd stable-imitation-policy-with-waypoints
```

Make sure you have Conda installed, or install it from [Anaconda Website](https://conda.io/projects/conda/en/latest/user-guide/install/linux.html).

### Mac
Create and activate a new conda environment from the `environment-mac.yml` file.
```
conda env create -f environment-mac.yml
conda activate IL-waypoint
```
Install packages required for the simulation. 
```
# Install MuJoCo
pip install mujoco

# Install robosuite
git clone https://github.com/ARISE-Initiative/robosuite.git
cd robosuite
git checkout v1.4.1_libero
pip install -r requirements.txt
pip install -r requirements-extra.txt
pip install -e .

# Install BDDL
cd ..
git clone https://github.com/StanfordVL/bddl.git
cd bddl
pip install -e .

# Install LIBERO
cd ..
git clone https://github.com/Lifelong-Robot-Learning/LIBERO.git
cd LIBERO
pip install -r requirements.txt
pip install -e .

# Install Robomimic
cd ..
git clone https://github.com/ARISE-Initiative/robomimic
cd robomimic
git checkout mimicplay-libero
pip install -e .

```
## Datasets

See [this](https://drive.google.com/drive/folders/1pUf4rRhM_E5hXXHynWmEhNyuBOxJXORY?usp=sharing) drive for the hdf5 datasets. Use the following commands to download the data.

```
cd data
gdown --folder https://drive.google.com/drive/folders/1pV-Lii52PF1djSSOAlLdCLpyS9zDAFIs?usp=drive_link
```
## Repository structure

To acquire a better understanding of the environment and features, you just need to clone the repository into your local machine. At first glance, the structure of the project appears below.

```bash
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── build/
├── environment-mac.yaml
├── environment.yaml
├── setup.py
├── stable-imitation-policy-with-waypoints # python package
│   ├── config/ # config files for imitate-task.py
│   ├── data/ # simulation datasets
│   ├── imitate-task.py
│   ├── lib/
│   │   ├── envs/
│   │   ├── learn_gmm_ds.py
│   │   ├── learn_nn_ds.py
│   │   ├── learn_ply_ds.py
│   │   ├── learn_rl_ds.py
│   │   ├── lipnet/
│   │   ├── nns/
│   │   ├── policy_interface.py
│   │   ├── rls
│   │   ├── seds/
│   │   ├── sos/
│   │   └── utils/
│   ├── res/ # saved policies
│   ├── sim
│   │   └── playback_robomimic.py
│   ├── src/
│   ├── train_waypoints.py
│   └── videos/
└── stable_imitation_policy_with_waypoints.egg-info
```
## Training

### config file
Create a config file with the following structure: 
```json
{
    "learner_type": "snds", # the policy to train
    "num_epochs": 10000, # the max number of epochs
    "data_dir": "data/dataset.hdf5", # the path to the hdf5 dataset of the task 
    "camera_names": ["agentview", "robot0_eye_in_hand"], # the cameras to render in the simulation
    "demos": [1], # the demos to train on
    "video_path": "videos/video.mp4", # the file to save the video to
    "multiplier": 0.01, # this value scales the input commands before they are applied by the controller
    "states": ["robot0_eef_pos", "robot0_eef_quat", "robot0_eef_vel_ang", "robot0_eef_vel_lin", "robot0_gripper_qpos"],
    "waypoints_dataset": "AWE_waypoints_dp_err005", # the name of the waypoint dataset in the hdf5 file
    "subgoals_dataset": "AWE_subgoals_dp_err005", # the name of the subgoal dataset in the hdf5 file
    "device": "cpu", # or cuda, or mps
    "plot": false, # whether to plot the trajectory
    "playback": true, # whether to playback the simulation video
    "video_skip": 5, # this value determines how many actions are skipped before a frame is saved to the video
    "model_names": ["waypoint-test-snds-subgoal0-21-08-11-50", "waypoint-test-snds-subgoal1-21-08-11-50"], # names of the pretrained models (optional)
    "model_dir": "res/" # directory of the pretrained models (optional)
}
```
Then, run the python script
```shell
python imitate-task.py --config path/to/config/file.json
```
## Known Issues

* In some cases the training loss doesn't reduce when training the model, but the problem can be resolved by running the code again. We are trying to solve this problem at the moment.
* Note that in proper training, the loss should hover around 5e-3 and lower, otherwise the Lyapunov function might not be trained properly. Always allow sufficient epochs, 3-5k at least, to achieve this result, and also for learning rate scheduler to complete its task.
  ```cmd
  Train > 0.007863 | Test > 0.005087 | Best > (0.007863, 24) | LR > 0.00099
  ```

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct, and the process for submitting **pull requests** to us.

## Citation

Please use the following BibTeX formatted **citation** for PLYDS:
```
@inproceedings{abyaneh2023learning,
  title={Learning Lyapunov-Stable Polynomial Dynamical Systems Through Imitation},
  author={Abyaneh, Amin and Lin, Hsiu-Chin},
  booktitle={7th Annual Conference on Robot Learning},
  year={2023}
}
```
and SNDS:
```
@article{abyaneh2024globally,
  title={Globally Stable Neural Imitation Policies},
  author={Abyaneh, Amin and Guzm{\'a}n, Mariana Sosa and Lin, Hsiu-Chin},
  journal={arXiv preprint arXiv:2403.04118},
  year={2024}
}
```

## Authors

* Alexandre St-Aubin
* Amin Abyaneh
* Hsiu-Chin Lin

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
