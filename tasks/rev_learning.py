#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This module contains various experimental environments used for testing 
human behavior.

Created on Thu Feb  22 14:50:01 2018

@author: Dimitrije Markovic
"""

import torch
from torch.distributions import Categorical

__all__ = [
        'SocialInfluence',
        'TempRevLearn'
]

class SocialInfluence(object):
    """Implementation of the social learning task
    """
    
    def __init__(self, stimuli, nsub=1, blocks=1, trials=120):
        
        self.trials = trials
        self.nsub = nsub

        # set stimuli 
        self.stimuli = stimuli
        
    def update_environment(self, block, trial, responses):
        """Generate stimuli for the current block and trial
        """        
        outcomes = self.stimuli['reliability'][block, trial]
        offers = self.stimuli['offers'][block, trial]
        
        self.stimulus = {'outcomes': outcomes,
                      'offers': offers}
    
        
    def get_stimulus(self, *args):
        """Returns dictionary of all stimuli values relevant for update of agent's beliefs.
        """
        return self.stimulus
    
class TempRevLearn(object):
    """Implementation of the temporal reversal learning task. 
    """
    
    def __init__(self, stimuli=None, nsub=1, blocks=1, trials=1000):
        self.trials = trials
        self.nsub = nsub
        
        # set stimuli
        self.stimuli = stimuli
        
    def likelihood(self, block, trial, responses):
        raise NotImplementedError
        
    def update_states(self, block, trial):
        raise NotImplementedError
        
    def get_offers(self, block, trial):
        
        if self.stimuli is not None:
            offers = self.stimuli['offers'][block, trial]
        else:
            cat = Categorical(logits=torch.zeros(2))
            offers = cat.sample((self.nsub,))
        
        return offers
    
    def update_environment(self, block, trial, responses):
        
        if self.stimuli is not None:
            rewards = self.stimuli['rewards'][block, trial]
            states = self.stimuli['states'][block, trial]
            
            hints = responses == 2
            nohints = ~hints
            
            outcomes = torch.zeros(self.nsub, dtype=torch.long)
            outcomes[nohints] = rewards[nohints, responses[nohints]]
            outcomes[hints] = states[hints] + 2
            
            response_outcome = [responses, outcomes]
        else:
            # update states
            self.update_states(block, trial)
            # generate outcomes            
            probs = self.likelihood(block, trial, responses)
            cat1 = Categorical(probs=probs)
            response_outcome = [responses, cat1.sample((self.nsub,))]
            
        return response_outcome
    
        