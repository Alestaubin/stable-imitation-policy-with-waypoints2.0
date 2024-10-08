#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time, os, copy
import numpy as np

import torch
import torch.nn as nn
import torch.optim as optim

from lib.policy_interface import PlanningPolicyInterface
from torch.utils.data import DataLoader, TensorDataset

from tqdm.auto import tqdm

from lib.nns.networks import NN, LNET
from lib.nns.euclidean_flows import init_sdsef_model
from lib.nns.deep_dynamics import init_snds_model

from lib.utils.utils import mse
from lib.utils.log_config import logger


class NL_DS(PlanningPolicyInterface):
    """ Approximation of a dynamical system using nonlinear approaches.

    Since a DS dataset can be seen as a time series data, with velocities acting as labels, NN
    networks sounds like a plausible option for estimating nonlinear DS.
    """

    def __init__(self, 
                 network: str = 'nn', 
                 data_dim: int = 2, 
                 device: str = 'cuda:0', 
                 eps: float = 0.01,
                 alpha: float = 0.01, 
                 relaxed: bool = False, 
                 goal: np.ndarray = None, 
                 fhat_layers=[256, 256, 256], 
                 lpf_layers=[64, 64]):
        """ Initialize a nonlinear DS estimator.

        Note: the 'nn' method is equivalent to using behavioral cloning.

        Args:
            network (str, optional): Network type. So far could be nn (Neural Network)
                or lstm (Recurrent Neural Networks).

            data_dim (int, optional): Dimension of the input data. Defaults to 2.
            plot_model (bool, optional): Choose to plot or not. Defaults to False.
        """
        self.__lpf = None
        self.__lpf_layers = lpf_layers
        self.__fhat_layers = fhat_layers
        self.__data_dim = data_dim

        # snds params
        self.__epsilon = eps
        self.__alpha = alpha
        self.__relaxed = relaxed

        # gpu params
        # self.__cuda = gpu
        self.__device = device
        logger.info(f'Switching to {self.__device} for computation')

        if goal is not None:
            #self.__goal  = torch.tensor(goal.astype(np.float32), device=self.__device)
            self.__goal = torch.tensor(goal, dtype=torch.float32, device=self.__device)
        else:
            self.__goal = torch.zeros(1, self.__data_dim, device=self.__device)

        # network module
        self.__network_type = network
        self.__nn_module: nn.Module = None
        self._initialize_network()
        self.__nn_module.to(self.__device)

        logger.info(f'{network.upper()} network initialized')
        self.__dataset: DataLoader = None

    def fit(self, trajectory: np.ndarray, velocity: np.ndarray, n_epochs: int = 200,
            batch_size: int = 128, show_stats: bool = True, stat_freq: int = 2,
            trajectory_test: np.ndarray = None, velocity_test: np.ndarray = None,
            clip_gradient: bool = True, clip_value_grad: float = 0.5, loss_clip: float = 1e3,
            stop_threshold: int = 3000, lr_initial: float = 0.001, lr_end_factor: float = 0.01):
        """ Fit a nonlinear model to estimate a dynamical systems.

        Args:
            trajectory (np.ndarray): Trajectory data in shape (samples, features).
            velocity (np.ndarray): Velocity data in shape (samples, features).
            show_ds (bool, optional): Whether to show the final DS or not. Defaults to False.
            title (str, optional): Plot title for the model. Defaults to None.
            show_stats (bool, optional): Show training statistics. Defaults to False.
        """

        # build the dataset
        self.__dataset = self._prepare_torch_dataset(trajectory, velocity, batch_size)

        if trajectory_test is not None:
            trajectory_test = torch.from_numpy(trajectory_test.astype(np.float32)).to(self.__device)
            velocity_test = torch.from_numpy(velocity_test.astype(np.float32)).to(self.__device)

            trajectory_test.requires_grad = True
            velocity_test.requires_grad = True

        # optimizer and scheduler
        optimizer = optim.Adam(self.__nn_module.parameters(), lr=lr_initial)
        scheduler = optim.lr_scheduler.LinearLR(optimizer, start_factor=1.0,
                                                end_factor=lr_end_factor,
                                                total_iters=n_epochs)
        criterion = nn.MSELoss()

        # start time
        logger.info('Starting the policy training sequence')
        start_time = time.time()

        best_train_loss = np.inf
        best_train_epoch = 0
        best_model = self.__nn_module
        best_lpf = self.__lpf

        # train the model
        self.__nn_module.train()

        # training epochs
        for epoch in (par := tqdm(range(n_epochs))):
            # iterate over minibatches
            train_losses = []

            for trajs_t, vels_t in self.__dataset:

                # forward pass
                optimizer.zero_grad()
                y_pred = self.__nn_module(trajs_t)

                # compute loss
                loss = criterion(y_pred, vels_t)
                train_losses.append(loss.item())

                if loss > loss_clip or loss == torch.nan:
                    self._initialize_network()
                    optimizer = optim.Adam(self.__nn_module.parameters(), lr=lr_initial)
                    logger.warn('Loss value is too large, reinitializing')
                    continue

                # backward pass
                loss.backward()

                # clip gradient based on norm
                if clip_gradient:
                    torch.nn.utils.clip_grad_norm_(
                        self.__nn_module.parameters(),
                        clip_value_grad
                    )

                # update parameters
                optimizer.step()

            scheduler.step()
            train_loss = np.mean(train_losses)

            # save the best model
            if best_train_loss - train_loss > 1e-6:
                best_train_epoch = epoch
                best_train_loss = train_loss
                best_model = copy.deepcopy(self.__nn_module)
                best_lpf = copy.deepcopy(self.__lpf)


            # tracking the learning process
            if show_stats and epoch % stat_freq == 0:
                par.set_description(f'Train > {(train_loss):.6f} | Test > {mse(self.__nn_module(trajectory_test), velocity_test) if trajectory_test is not None else 0:.6f} | Best > ({best_train_loss:.6f}, {best_train_epoch}) | LR > {scheduler.get_last_lr()[0]:.5f}')

            # keep track of stalled progress
            if epoch - best_train_epoch >= stop_threshold:
                logger.info(f'No progress for a while, quitting the training loop')
                break

            # react to nan loss values
            if train_loss == torch.nan or train_loss == torch.inf:
                logger.info(f'Nan/Inf loss function acquired, reinitializing...')
                self._initialize_network()


        total_time = time.time() - start_time
        logger.info(f'Training concluded in {total_time:.4f} seconds')

        self.__nn_module = best_model
        self.__lpf = best_lpf

    def predict(self, trajectory: np.ndarray):
        """ Predict estimated velocities from learning NN_DS.

        Args:
            trajectory (np.ndarray): Trajectory in shape (sample size, dimension).

        Returns:
            np.ndarray: Estimated velocities in shape (sample size, dimension).
        """

        #x = torch.from_numpy(trajectory.astype(np.float32)).to(self.__device)
        x = torch.tensor(trajectory, dtype=torch.float32, device=self.__device)
        x.requires_grad = True

        res = self.__nn_module(x)
        return res.detach().cpu().numpy()

    def lpf(self, x: np.ndarray = np.array([0, 0])):
        """Return the Lyapunov function.

        Args:
            x (np.ndarray): Trajectory points

        Returns:
            np.float: Lyapunov function values.
        """

        if self.__lpf is None:
            return None

        x = torch.from_numpy(x.astype(np.float32))
        x.requires_grad = True

        x = x.to(device=self.__device)
        x = x.reshape(1, self.__data_dim)
        res = self.__lpf.forward(x)
        return res.detach().cpu().numpy()

    def load(self, model_name: str, dir: str = '../res'):
        """ Load the torch model.

        Args:
            model_name (str): Name of the model.
            dir (str, optional): Load directory. Defaults to '../res'.
        """
        if self.__network_type == 'sdsef': # TODO: Bug in sds-ef saving process
            self.__nn_module.load_state_dict(torch.load(os.path.join(dir, f'{self.__network_type}', f'{model_name}.pt')))
            self.__nn_module.eval()
        else:
            self.__nn_module = torch.load(os.path.join(dir, f'{self.__network_type}',
                                                   f'{model_name}.pt'))


    def save(self, model_name: str, dir: str = '../res'):
        """ Save the torch model.

        Args:
            model_name (str): Name of the model.
            dir (str, optional): Save directory. Defaults to '../res'.
        """

        if self.__network_type == 'sdsef': # TODO: Bug in sds-ef saving process
            torch.save(self.__nn_module.state_dict(), os.path.join(dir, f'{self.__network_type}',f'{model_name}.pt'))
        else:
            os.makedirs(os.path.join(dir, f'{self.__network_type}'), exist_ok=True)
            torch.save(self.__nn_module, os.path.join(dir, f'{self.__network_type}',
                                                  f'{model_name}.pt'))


    def _initialize_network(self):
        if self.__network_type == 'nn':
            self.__nn_module = NN(input_shape=self.__data_dim, output_shape=self.__data_dim)
        elif self.__network_type == 'lnet':
            self.__nn_module = LNET(input_shape=self.__data_dim, output_shape=self.__data_dim)
        elif self.__network_type == 'sdsef':
            self.__nn_module = init_sdsef_model(input_dim=self.__data_dim, device=self.__device, goal=self.__goal)
        elif self.__network_type == 'snds':
            self.__nn_module, self.__lpf  = init_snds_model(
                device=self.__device, 
                lsd=self.__data_dim, 
                fhat_layers=self.__fhat_layers, 
                lpf_layers=self.__lpf_layers, 
                alpha=self.__alpha, 
                eps=self.__epsilon,
                relaxed=self.__relaxed, 
                goal=self.__goal)
        else:
            raise NotImplementedError(f'Network type {self.__network_type} is not available!')


    def _prepare_torch_dataset(self, trajs: np.ndarray, vels: np.ndarray, batch_size: int):
            """ Convert npy data to tensor dataset.

            NOTE: Batch size is fixed for small dataset

            Args:
                trajs (np.ndarray): Demonstrated trajectories.
                vels (np.ndarray): Demonstrated velocities.
                batch_size (int): Size of data batches for the loader.
            """

            # convert npy to tensor
            #x = torch.from_numpy(trajs.astype(np.float32))
            #y = torch.from_numpy(vels.astype(np.float32))
            x = torch.tensor(trajs, dtype=torch.float32, device=self.__device)
            y = torch.tensor(vels, dtype=torch.float32, device=self.__device)

            #x = x.to(device=self.__device)
            #y = y.to(device=self.__device)

            x.requires_grad = True
            y.requires_grad = True

            # generate a dataloader
            dataset = TensorDataset(x, y)
            batch_size = batch_size if batch_size < trajs.shape[0] else trajs.shape[0]
            return DataLoader(dataset, batch_size=batch_size, shuffle=True)

