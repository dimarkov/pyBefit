"""This module contains the hierarchical implementations of the parametric model.
"""

import pandas as pd

import torch
from torch import zeros, ones
from torch.distributions import constraints, biject_to

import pyro.distributions as dist
from pyro import sample, param, plate
from pyro.distributions.util import sum_rightmost

from .infer import Inferrer

__all__ = [
    'Horseshoe'        
]

class Horseshoe(Inferrer):
    
    def __init__(self, agent, stimulus, responses, mask=None, fixed_params=None):
        super(Horseshoe, self).__init__(agent, stimulus, responses, mask=mask, fixed_params=fixed_params)

    def model(self):
        """
        Generative model of behavior with a hierarchical (horseshoe)
        prior over free model parameters.
        """
        runs = self.runs  # number of independent runs of experiment
        npar = self.npar  # number of parameters

        # define hyper priors over model parameters.
        # each model parameter has a hyperpriors defining group level mean
        m = param('m', zeros(npar))
        s = param('s', ones(npar), constraint=constraints.positive)
        mu = sample('mu', dist.Normal(m, s).to_event(1))

        # define prior uncertanty over model parameters and subjects
        a = param('a', 2*ones(npar), constraint=constraints.positive)
        b = param('b', ones(npar), constraint=constraints.positive)
        tau = sample('tau', dist.Gamma(a, b).to_event(1))

        # define prior mean over model parametrs and subjects
        with plate('runs', runs):
                locs = sample('locs', dist.Normal(mu, 1/torch.sqrt(tau)).to_event(1))
        

        if self.fixed_values:
            x = zeros(runs, self.agent.npar)
            x[:, self.locs['fixed']] = self.values
            x[:, self.locs['free']] = locs
        else:
            x = locs

        self.agent.set_parameters(x)
        
        for b in range(self.nb):
            for t in range(self.nt):
                #update single trial
                offers = self.stimulus['offers'][b, t]
                self.agent.planning(b, t, offers)
                
                logits = self.agent.logits[-1]
                
                outcomes = self.stimulus['outcomes'][b, t]
                responses = self.responses[b, t]
                
                mask = self.stimulus['mask'][b, t]
                
                self.agent.update_beliefs(b, t, [responses, outcomes], mask=mask)
                
                notnans = self.notnans[b, t]                
                
                if torch.any(notnans):
                    lgs = logits[notnans]
                    res = responses[notnans]
                    with plate('responses_{}_{}'.format(b, t), len(res)):
                        sample('obs_{}_{}'.format(b, t), dist.Categorical(logits=lgs), obs=res)
            
    def guide(self):
        """Approximate posterior for the horseshoe prior. We assume posterior in the form 
        of the multivariate normal distriburtion for the global mean and standard deviation
        and multivariate normal distribution for the parameters of each subject independently.
        """
        nsub = self.runs #number of subjects
        npar = self.npar #number of parameters
        trns = biject_to(constraints.positive)

        
        m_hyp = param('m_hyp', zeros(2*npar))
        st_hyp = param('scale_tril_hyp', 
                              torch.eye(2*npar), 
                              constraint=constraints.lower_cholesky)
        hyp = sample('hyp', dist.MultivariateNormal(m_hyp, 
                                                  scale_tril=st_hyp), 
                            infer={'is_auxiliary': True})
        
        unc_mu = hyp[:npar]
        unc_tau = hyp[npar:]
    
        c_tau = trns(unc_tau)
    
        ld_tau = trns.inv.log_abs_det_jacobian(c_tau, unc_tau)
        ld_tau = sum_rightmost(ld_tau, ld_tau.dim() - c_tau.dim() + 1)
    
        mu = sample("mu", dist.Delta(unc_mu, event_dim=1))
        tau = sample("tau", dist.Delta(c_tau, log_density=ld_tau, event_dim=1))
        
        m_locs = param('m_locs', zeros(nsub, npar))
        st_locs = param('scale_tril_locs', torch.eye(npar).repeat(nsub, 1, 1), 
                   constraint=constraints.lower_cholesky)

        with plate('subjects', nsub):
            locs = sample("locs", dist.MultivariateNormal(m_locs, scale_tril=st_locs))
        
        return {'mu': mu, 'tau': tau, 'locs': locs}
            
    def sample_posterior(self, labels, n_samples=10000):
        """Generate samples from posterior distribution.
        """
        nsub = self.runs
        npar = self.npar
        assert npar == len(labels)
        
        keys = ['locs', 'tau', 'mu']
        
        trans_pars = zeros(n_samples, nsub, npar)
        
        mu_group = zeros(n_samples, npar)
        tau_group = zeros(n_samples, npar)
        
        for i in range(n_samples):
            sample = self.guide()
            for key in keys:
                sample.setdefault(key, ones(1))
                
            mu = sample['mu']
            tau = sample['tau']
            locs = sample['locs']
            
            trans_pars[i] = locs.detach()
            
            mu_group[i] = mu.detach()
            tau_group[i] = tau.detach()
        
        subject_label = torch.arange(1, nsub+1).repeat(n_samples, 1).reshape(-1)
        tp_df = pd.DataFrame(data=trans_pars.reshape(-1, npar).numpy(), columns=labels)
        tp_df['subject'] = subject_label.numpy()
        
        g_df = pd.DataFrame(data=mu_group.numpy(), columns=labels)
        tg_df = pd.DataFrame(data=tau_group.numpy(), columns=labels)
        
        return (tp_df, g_df, tg_df)
    
    def _get_quantiles(self, quantiles):
        """
        Returns posterior quantiles each latent variable.

        :param quantiles: A list of requested quantiles between 0 and 1.
        :type quantiles: torch.Tensor or list
        :return: A dict mapping sample site name to a list of quantile values.
        :rtype: dict
        """
        
        self.means = [param('m_locs'), param('m_hyp')]
        self.stds = [param('scale_tril_hyp'), param('scale_tril_locs')]
        
        quantiles = torch.tensor(quantiles).reshape(1, 3)

        
        m_locs = param('m_locs').reshape(-1, 1)
        s_locs = param('scale_tril_locs').diagonal(dim1=-2, dim2=-1).reshape(-1, 1)
        
        latents = dist.Normal(m_locs, s_locs).icdf(quantiles).reshape(self.runs, -1, 3)
        result = {'locs': latents}

        m_hyp = param('m_hyp').reshape(-1, 1)
        s_hyp = param('scale_tril_hyp').diagonal(dim1=-2, dim2=-1).reshape(-1, 1)
        
        latents = dist.Normal(m_hyp, s_hyp).icdf(quantiles).reshape(-1, 1)
        
        result['mu'] = latents[:self.npar]
        result['tau'] = latents[self.npar:].exp()
                
        return result