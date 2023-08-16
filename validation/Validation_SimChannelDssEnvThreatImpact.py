# -*- coding: utf-8 -*-
"""
Created on Fri July 1 09:17:05 2022

@author: abhijeetsahu

This environment would merge both Simpy and OpenDSS environment.. Current implementation is a dummy merge..Still need to update
"""

import os
import sys
directory = os.path.dirname(os.path.realpath(__file__))
desktop_path = os.path.dirname(os.path.dirname(directory))
sys.path.insert(0,desktop_path+'\\DSS-SimPy-RL')
import collections

import gym
from envs.openDSSenv import openDSSenv
from envs.simpy_env.CyberWithChannelEnvSB_123 import CyberEnv
from envs.simpy_env.generate_network import create_network,create_network2
import opendssdirect as dss
import random
import networkx as nx
import concurrent.futures
from functools import partial
import threading
import pandas as pd
from queue import Queue
import numpy as np
import statistics
from gym import error, spaces, utils
from gym.utils import seeding
import scipy.io

# TO IMPLEMENT
# This class will be used to map the cyber components into the physical space.
# All the Data Concentrator would be connected to certain buses, lines, capacitor banks in the system 
# Depending on the line fault, the cyber simulator would be initiating an event packet...
# And later when the switches are opened or closed, every zone would acknowledge the operation of the switch.

# How to incorporate the inter-env interaction. The best method is to use an interconnecting Queues... One for phy communicating cyb another vice-versa
# What are the information we want to pass across these simulator?
# Depending on the Line fault and switch loc, the cyber emulator will pick the Data concentrator to first forward the line info, followed by ACK for switching action (PHY=>CYB)
# Based on the succesful packet transmission, the phy side action will be executed. (CYB===>PHY)
def CyberPhysicalMapping():
    # read the bus file
    fp = desktop_path+'\\DSS-SimPy-RL\\cases\\123Bus_Simple\\Buses_Pyomo.csv'
    bi = pd.read_csv(fp)
    
    bus_info = bi.set_index('Buses')['Zone'].to_dict()

    fp2 = desktop_path+'\\DSS-SimPy-RL\\cases\\123Bus_Simple\\Lines_data_Pyomo.csv'
    li = pd.read_csv(fp2)
    line_info = li.set_index('Lines').T.to_dict('list')


    return bus_info, line_info

#### Dummy Variant Serial Execution###################

class CyberPhysicalEnvDummy:
    def __init__(self, cenv, penv, compzones):
        self.envs = []
        self.envs.append(cenv)
        self.envs.append(penv)
        self.compzones = comp_zones

    def reset(self):
        for env in self.envs:
            env.reset()

    def step(self, actions):
        obs = []
        rewards = []
        dones = []
        infos = []

        for env, ac in zip(self.envs, actions):
            ob, rew, done, info = env.step(ac)
            obs.append(ob)
            rewards.append(rew)
            dones.append(done)
            infos.append(info)

            if done:
                env.reset()

        return obs, rewards, all(dones), infos

# use multi threading parallel execution#####################
class CyberPhysicalEnvMT(gym.Env):
    def __init__(self, cenv, penv, comp_zones):
        self.envs = []
        cenv.comp_zones = comp_zones
        self.envs.append(cenv)
        self.envs.append(penv)
        self.comp_zones = comp_zones
        self.map_sw = {0:'Sw2',1:'Sw3',2:'Sw4',3: 'Sw5',4:'Sw6',5:'Sw7',6:'Sw8'}
        self.pc_queue = Queue() # pass data from phy env to cyb env
        self.cp_queue = Queue() # pass data from cyb env to phy env
        
        self.observation_space = spaces.Box(low=0, high=1000000.0, shape=(len(cenv.channels) + len(penv.critical_loads),), dtype=np.float32)
        self.action_space = spaces.MultiDiscrete([cenv.deviceCount, 5,len(penv.switch_names)])

    def reset(self):
        obs = []
        counter = 0
        for env in self.envs:
            if counter == 0:
                obs = list(env.reset())
            else:
                obs.extend(env.reset())
            counter+=1
        return np.array(obs)

    def step(self, actions):
        #print(actions)
        obs = []
        rewards = []
        dones = []
        infos = ''

        result={}
        #print(self.map_sw[actions[2]])
        phy_thread =threading.Thread(target=self.envs[1].step, args= (self.map_sw[actions[2]],result, self.pc_queue, self.cp_queue))
        phy_thread.start()

        cyb_thread = threading.Thread(target=self.envs[0].step, args= (actions[0:2],result, self.pc_queue, self.cp_queue))
        cyb_thread.start()

        phy_thread.join()
        cyb_thread.join()

        res= []
        od_res = collections.OrderedDict(sorted(result.items()))
        for k, v in od_res.items():
            res.append(v)
        counter = 0
        for ob, rew, done, info in res:
            if counter == 0:
                obs= list(ob)
            else:
                obs.extend(ob)
            rewards.append(rew)
            dones.append(done)
            if counter == 0:
                infos=str(info)
            else:
                infos+=str(info)
            counter+=1
        #print('{0} {1} {2} {3}'.format(obs, rewards[0]+statistics.mean(rewards[1]), all(dones), infos))
        information = {}
        #information["episode"] = infos
        #return np.array(obs), rewards[0]+statistics.mean(rewards[1]), all(dones), information
        return np.array(obs), rewards[0]+rewards[1], all(dones), information


if __name__ == '__main__':

    bi, li = CyberPhysicalMapping()
    comp_zones = bi
    for i,(k,v) in enumerate(li.items()):
        comp_zones[k] = bi[v[0]]

    comp_zones['C83'] = bi['83']
    comp_zones['C88a'] = bi['88']
    comp_zones['C90b'] = bi['90']
    comp_zones['C92c'] = bi['92']

    # Create the Cyber Network
    G = create_network2()
    #cenv = CyberEnv(provided_graph=G, channelModel=True,envDebug=False, R2_qlimit=40, ch_bw = 1000,with_threat=True,comp_zones=comp_zones)
    cenv = CyberEnv(provided_graph=G, channelModel=True,envDebug=False, R2_qlimit=100, ch_bw = 2000,with_threat=True)
    
    der = True
    # Create the Physical Network
    dss_data_dir = desktop_path+'\\DSS-SimPy-RL\\cases\\123Bus_Simple\\'
    dss_master_file_dir = 'Redirect ' + dss_data_dir + 'IEEE123Master.dss'

    if der:
        dss_data_dir = desktop_path+'\\DSS-SimPy-RL\\cases\\123Bus_SimpleMod\\'
        dss_master_file_dir = 'Redirect ' + dss_data_dir + 'IEEE123Master.dss'

    dss.run_command(dss_master_file_dir)
    circuit = dss.Circuit
    #critical_loads_bus = ['58','59','99','100','88','93','94','78','48','50', '111','114', '37','39']
    critical_loads_bus = ['57','60']
    capacitor_banks =['C83', 'C88a', 'C90b','C92c']
    # switch from and two buses, with the first 6 are normally closed and the last two are normally open
    switches = { 0: ['150r','149'], 1: ['13','152'], 2: ['18','135'], 3: ['60','160'], 4: ['97','197'], 5: ['61','61s'], 6: ['151','300'], 7: ['54','94'] }

    switch_names =[]
    for k,sw in enumerate(switches):
        switch_names.append('Sw'+str(k+1))

    line_faults = ['L55','L68', 'L58', 'L77', 'L45', 'L101', 'L41']
    #line_faults = ['L55']
    ders = ['35','48','64','78','95','108']
    penv = openDSSenv(_dss = dss, _critical_loads=critical_loads_bus, _line_faults =line_faults, _switch_names = switch_names, _capacitor_banks = capacitor_banks,_ders=ders)

    # This is the creation of mixed environment
    #cyber_phy_env = CyberPhysicalEnvDummy(cenv, penv, comp_zones)

    

    episodes = 50
    max_episode_len = 100

    # change the threat intensity and channel BW
    for threat in range(3,4,1):
        # change the contingency type
        for c in range(1,5,1):
            cenv.ch_bw = 2500
            cenv.device_compromised = threat
            penv.contingency = c
            cyber_phy_env= CyberPhysicalEnvMT(cenv, penv,comp_zones)
            agg_episode_len = []
            app_episode_len_all = []
            results={}
            #sucess_info=[]
            sucess=0
            for i in range(episodes):
                cyber_phy_env.reset()
                #print('observation : {}'.format(state))
                action_index = random.randint(1,2)
                done = False
                ctr = 0
                episodic_reward = []
                episode_length=0
                print('Episode {}'.format(i+1))
                while not done and  ctr < max_episode_len:
                    actions = []
                    ctr+=1
                    # phy
                    # randomly select an action for time-being until we train an agent
                    phy_action = random.choice(switch_names[0:])
                    
                    # randomly pick a router to modify the next_hop
                    router_id = random.randint(0,cenv.deviceCount-1)
                    
                    # currently random:  to implement  get the next hop from the shortest path algorithm
                    rnd_action_index = random.randint(0, len(cenv.routers[router_id].out)-1)

                    shortest_path_action_index = nx.single_source_shortest_path(cenv.G, router_id)['PS'][1]

                    rnd_action = [router_id,rnd_action_index]

                    if shortest_path_action_index != 'PS' and False:
                        rtr_id = 'R'+str(shortest_path_action_index)
                        rtr_ix = [ix for (ix,item) in enumerate(cenv.routers[router_id].out) if item.id == rtr_id][0]
                        #action = {'device':router_id, 'next_hop':rtr_ix}
                        cyb_action = [router_id,rtr_ix]
                    else:
                        cyb_action = rnd_action

                    # mixed environment step
                    actions.append(cyb_action)
                    cyb_action.append(list(cyber_phy_env.map_sw.values()).index(phy_action))
                    actions = cyb_action

                    next_state, reward, done, info = cyber_phy_env.step(actions)
                    #print('Fusion State {0} Episode Termination State : {1}'.format(next_state, done))
                    #print(reward[1])
                    episodic_reward.append(reward)
                    episode_length+=1
                app_episode_len_all.append(ctr)
                if ctr < max_episode_len:
                    sucess+=1
                    agg_episode_len.append(ctr)
            
                #print('Average Episode Reward {0} and Episode Length {1}'.format(statistics.mean(episodic_reward), episode_length))
            #sucess_info.append(sucess)
            if len(agg_episode_len) == 0:
                results['avg_episode_len'] = 100
            else:
                results['avg_episode_len'] = statistics.mean(agg_episode_len)
            results['avg_episode_len_all'] = statistics.mean(app_episode_len_all)
            results['succ_rate'] = sucess/episodes
            print('success rate {0} avg episode len {1} episode len only success {2}'.format(sucess/episodes, statistics.mean(app_episode_len_all),results['avg_episode_len']))
            scipy.io.savemat('Contingency_Type_'+str(c)+'_Rtr_Comp_'+str(threat)+'_goal_cp_Rql_100_remove_unsucessful.mat',results)
                