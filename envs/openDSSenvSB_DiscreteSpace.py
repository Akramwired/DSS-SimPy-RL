# -*- coding: utf-8 -*-
"""
Created on Wed Jun 15 18:08:05 2022

@author: abhijeetsahu

This environment is created for episodic interaction of the OpenDSS simulator for training RL agent, similar to an Open AI Gym environment
"""

from queue import Queue
from random import random
from xml.etree.ElementTree import TreeBuilder
import opendssdirect as dss
import os
import math
import csv
import re
import itertools
import pandas as pd
import numpy as np
import sys
directory = os.path.dirname(os.path.realpath(__file__))
desktop_path = os.path.dirname(os.path.dirname(directory))
sys.path.insert(0,desktop_path+'\DSS-SimPy-RL')
#from utils.resilience_graphtheory import GraphResilienceMetric
import logging
import random
import gym
from gym import spaces

import matplotlib.pyplot as plt

import networkx as nx
import opendssdirect as dss
import re
from collections import defaultdict
from statistics import mean

#from torch import int8
from envs.resilience_graphtheory import GraphResilienceMetric
from envs.generate_scenario import *
from queue import Queue

class openDSSenv(gym.Env):
    metadata = {'render.modes': ['human']}

    def __init__(self, _dss, _critical_loads, _line_faults,_switch_names,_capacitor_banks,debug=False,contingency=1,load_lb=0.8, load_ub=1.2,_ders=None):
        """
        This function is the constructor of the opendss environment. 

        Parameters
        ----------
        _dss : The opendss object based on the scenario considered.
        _critical_loads : The list of load buses whose voltage profile needed to be stable
        _line_faults : The list of the transmission line that are considered for contingency
        _switch_names : The list of the controllable switch
        _capacitor_banks : The list of capacitor banks considered for contingency
        """
        print('initializing the 123-bus env')
        self.change_contingency_freq = 1
        self.episode_counter = 0
        self.dss = _dss
        self.circuit = _dss.Circuit
        self.critical_loads = _critical_loads
        self.line_faults = _line_faults
        self.current_line_faults = []
        #self.switch_names_all = _switch_names
        self.switch_names = _switch_names
        # This makes sure we do not remove the main switch
        #self.switch_names.remove('Sw1')
        self.capacitor_banks = _capacitor_banks
        self.ders = _ders
        self.load_names = list(self.dss.Loads.AllNames())
        self.switch_status = []
        self.debug = debug
        self.contingency = contingency
        self.load_lower_bound = load_lb
        self.load_upper_bound = load_ub

        self.lf_info = np.zeros((len(self.line_faults),),dtype=int)
        # the substraction of 1 is due to keep the switch connected to substation intact
        n_actions = len(_switch_names)

        self.action_space = spaces.Discrete(8)

        # primarily to store voltage and power injection values of the critical load
        self.observation_space = spaces.MultiBinary(len(self.critical_loads)+len(self.line_faults))
        #self.observation_space = spaces.Box(low=0, high=2, shape=(len(self.critical_loads),), dtype=np.float32)

        #print('Open DSS Env initialized')


    # here we try to incorporate sequential switching action (action space = {No. of switches}) or else the action space will be 2^{No. of switches}
    def step(self, action, result = {} , pc_queue = Queue(), cp_queue = Queue(), bypass_result = True,get_current_state=False):
        """
        This function executes the selected action on the environment. In this environment the action are limited to closing and opening
        of the controllable switch. This function call would transition of the state to next state, and the reward is computed. Unless 
        we learn a reward function we can take some existing resilience metric. The agent reaches the goal when all the critical load
        buses satisfies the voltage criteria. In most of the prior RL work the voltage limit criteria is incorporated through the
        reward function/in the form of cost.

        Parameters
        ----------
        action: The controllable switch name to CLOSE
        """

        # obtain the voltage of critical load before switching
        if isinstance(action,np.int64) or isinstance(action,np.int32) or isinstance(action,int):
            #print(action)
            #print(self.switch_names_all)
            action = self.switch_names[action]
        #print(action)
        volt_before_switching = []
        for cl in self.critical_loads:
            volt_before_switching.append(np.mean(get_Vbus(self.dss, self.circuit,cl)))
            #volt_before_switching.append(get_Vbus(self.dss, self.circuit,cl))
        volt_critical_loads_before_Switching_bin = transform_to_binary(volt_before_switching)

        #print('current state {0}'.format(transform_to_binary(volt_before_switching)))
        # execute the action and move to next state
        # close_switch(self.dss,self.circuit, action,self.switch_names)

        # execute the action on only one switch
        close_one_switch(self.dss, self.circuit, action, self.critical_loads)

        # get the critical node voltages
        volt_critical_loads = []

        # convert the current circuit into networkx graph
        grm = GraphResilienceMetric(_dss = self.dss)

        # compute the resilience metric
        #lf = (map(lambd x : x.lower(), self.current_line_faults))
        lf = [x.lower() for x in self.current_line_faults]
        #switch_status = (map(lambda x : x.lower(), action))
        self.switch_status.append(action.lower())
        #bcs = grm.compute_bc(list(lf),list(switch_status))
        #cls = grm.compute_cl(list(lf),list(switch_status))
        #ebcs = grm.compute_ebc(list(lf),list(switch_status))

        #bcs = grm.compute_bc(lf,self.switch_status)
        #cls = grm.compute_cl(lf,self.switch_status)
        #ebcs = grm.compute_ebc(lf,self.switch_status)

        #print('Average BC : {0}, Average CL : {1}, Average EBC : {2}'.format(str(np.mean(bcs)),str(np.mean(cls)),str(np.mean(ebcs)) ))

        for cl in self.critical_loads:
            volt_critical_loads.append(np.mean(get_Vbus(self.dss, self.circuit,cl)))
        if self.debug:
            print('Voltage Critical Loads : '+str(volt_critical_loads))

        satisfy_volt, v_err = voltage_satisfiability_easy(volt_critical_loads)

        volt_critical_loads_bin = transform_to_binary(volt_critical_loads)

        # this is temp..we will learn reward
        '''
        if satisfy_volt:
            reward = 20.0
        else:
            reward = -np.abs(v_err)
        '''
        # new reward model to try
        if satisfy_volt:
            reward = 20.0
        else:
            reward = 0
            for v in list(volt_critical_loads_bin):
                if v == 0:
                    reward-=1.0
                else:
                    reward+=0.0
        #reward = (-np.abs(v_err), np.mean(bcs), np.mean(cls), np.mean(ebcs))
        done = False
        info = {'lf':lf,'ss':self.switch_status}

        logging.info('Step Successful')

        

        #return volt_before_switching, volt_critical_loads, reward, done, info
        if result is not None:
            result[1] = (volt_critical_loads,reward,done,info)
            #result[1] = (volt_critical_loads,reward,done,info)
        pc_queue.put(info)

        volt_critical_loads_bin_merged = np.append(volt_critical_loads_bin,self.lf_info)
        result[1] = (volt_critical_loads_bin_merged,reward,done,info)

        if satisfy_volt:
            done = True
            #print('***************End of Phy********************')
            logging.info('Reached goal')
            info = {'lf':lf,'ss':self.switch_status,'terminal_observation':volt_critical_loads_bin_merged}
            result[1] = (volt_critical_loads_bin_merged,reward,done,info)

        if result is not None and not bypass_result:
            return volt_critical_loads_bin_merged, reward, done, info, result
        elif get_current_state:
            return np.append(volt_critical_loads_before_Switching_bin,self.lf_info),volt_critical_loads_bin_merged, reward, done, info
        else:
            #print(volt_critical_loads_bin_merged, reward, done, info)
            return volt_critical_loads_bin_merged, reward, done, info

    def reset(self):
        """
        This function resets the environment for a new episode where following things are performed:
        a) First all the controllable switches are opened
        b) Randomize the load profile
        c) based on a certain frequency a contingency is caused. Either single, double or mix
        d) the environment moves to the next state based on the contingency which acts as the initial state of the episode
        """
        dss_data_dir = desktop_path+'\\DSS-SimPy-RL\\cases\\123Bus_SimpleMod\\'
        dss_master_file_dir = 'Redirect ' + dss_data_dir + 'IEEE123Master.dss'

        dss.run_command(dss_master_file_dir)

        self.dss = dss

        self.episode_counter+=1
        # for resetting the environment
        #print(" Setting up the new environment")
        self.switch_status = []
        self.current_line_faults=[]

        # opening up all switches
        #print(self.switch_names[1:])
        open_switch_all(self.dss,self.circuit, self.switch_names[1:])

        # every time the environment is reset a new scenario is loaded
        randomize_load(self.dss, self.load_names, self.load_lower_bound, self.load_upper_bound)
        logging.info('New Loads Set')
    
        # after a certain episodes cause the contingencies
        if self.episode_counter % self.change_contingency_freq == 0:
            #r = random.randint(1,1)

            # randomly pick a line to cause fault from line_faults
            lf = random.choice(self.line_faults)
            #lf = 'L101'
            
            if self.contingency == 1:
                single_contingency(dss,str(lf))
                self.current_line_faults.append(str(lf))
                if self.debug:
                    print ('Contingency : Line Fault '+str(lf))

            elif self.contingency == 2:
                equal = True
                while equal:                    
                    lf2 = random.choice(self.line_faults)
                    if lf!=lf2:
                        equal=False
                double_contingency(dss,[str(lf),str(lf2)])
                self.current_line_faults.extend([str(lf),str(lf2)])
                if self.debug:
                    print ('Contingency : Line Faults '+str(lf)+' and '+str(lf2))

            elif self.contingency==3:
                if self.ders is None:
                    cb = random.choice(self.capacitor_banks)
                    mix_contingency(dss,lf,cb)
                    self.current_line_faults.append(str(lf))
                    if self.debug:
                        print ('Contingency : Line Fault '+str(lf)+' and CB outage'+str(cb))
                else:
                    der = random.sample(self.ders,5)
                    mix_contingency2(dss,lf,der)
                    self.current_line_faults.append(str(lf))
                    if self.debug:
                        print ('Contingency : Line Fault '+str(lf)+' and DER outage'+str(der))
            elif self.contingency==4:
                lfs = random.sample(self.line_faults,3)
                self.current_line_faults.extend(lfs)
                triple_contingency(dss,lfs)
                if self.debug:
                    print ('Contingency : Line Fault '+str(lf)+' and DER outage'+str(der))
            
        observation = []
        for cl in self.critical_loads:
            observation.append(np.mean(get_Vbus(self.dss, self.circuit,cl)))
            
        observation_bin = transform_to_binary(observation)
        logging.info('Reset complete \n')

        
        for i,lf in enumerate(self.line_faults):
            if lf in self.current_line_faults:
                self.lf_info[i] = 1
            else:
                self.lf_info[i] = 0
        merged_state = np.append(observation_bin,self.lf_info)
        return merged_state

    def render(self, mode ='human', close=False):
        """
        This function renders a simplistic visual of the environment, where based on the voltage profile, the network node colors would change

        Parameters
        ----------
        mode : currently set to 'human' mode
        close : boolean to enable or disable rendering of the nevironment visuals
        """
        grm = GraphResilienceMetric(_dss = self.dss)
        # line faults
        line_faults = []

        # extract from action
        switches_on = []

        grm.draw_network(line_faults,switches_on)



def transform_to_binary(observation_actual):
    """
    This function converts the observation space to multibinary space format
    """
    obs_mb = np.zeros((len(observation_actual),),dtype=int)
    for i,x in enumerate(observation_actual):
        if x > 0.0:
            obs_mb[i] = 1
    return obs_mb

        

def single_contingency(dss, lf):
    """
    This function causes a single line contingency

    Parameters
    ----------
    dss : opendss network 
    lf : the transmission line that undergoes line fault
    """
    cause_line_fault(dss,str(lf))

def double_contingency(dss,lfs):
    """
    This function causes a double contingency where two line fault occurs

    Parameters
    ----------
    dss : opendss network 
    lfs : the list of transmission lines that encounters fault
    """
    for lf in lfs:
        cause_line_fault(dss,lf)

def triple_contingency(dss,lfs):
    """
    This function causes a double contingency where two line fault occurs

    Parameters
    ----------
    dss : opendss network 
    lfs : the list of transmission lines that encounters fault
    """
    for lf in lfs:
        cause_line_fault(dss,lf)


def mix_contingency(dss,lf,cb):
    """
    This function causes a mixed contingency where a line fault occurs along with one capacitor bank is shut down

    Parameters
    ----------
    dss : opendss network 
    lf : the transmission line that undergoes line fault
    cb : the capacitor bank that goes down
    """
    cause_line_fault(dss,str(lf))
    cb_outage(dss,str(cb))

def mix_contingency2(dss,lf,der):
    """
    This function causes a mixed contingency where a line fault occurs along with one capacitor bank is shut down

    Parameters
    ----------
    dss : opendss network 
    lf : the transmission line that undergoes line fault
    der : set of der that goes down
    """
    cause_line_fault(dss,str(lf))
    #print('Der out {0}'.format(der))
    der_outage(dss,str(der))
   






    
