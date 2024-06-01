import os
import numpy as np
import pandas as pd


class Globals:
    def __init__(self):
        self.samplename = 'p5894'
        self.mintime = 21342.39
        self.maxtime = 21754.89
        self.mindisp = None
        self.maxdisp = None
        self.section_id = '5894001'
        self.k = 0.00153
        self.lc = 125
        self.rootpath = os.path.join(os.path.expanduser('~'), 'PycharmProjects', 'mcmcrsf_xfiles')
        self.vel_windowlen = 40
        self.filter_windowlen = 10
        self.q = 5
        self.ndr = 100
        self.nch = 2
        self.ntune = 2
        self.ncores = 4
        self.sim_name = f'out_{self.ndr}d{self.nch}ch_{self.section_id}'
        self.mu_sim = None
        self.threshold = 0.23

    def make_path(self, *args):
        return os.path.join(self.rootpath, *args)

    def get_output_storage_folder(self):
        p = self.make_path('mcmc_out', self.samplename, self.sim_name)

        isExisting = os.path.exists(p)

        if isExisting is False:
            print(f'directory does not exist, creating new directory --> {p}')
            os.makedirs(p)
            return p
        elif isExisting is True:
            print(f'directory exists, all outputs will be saved to existing directory and any existing files will be '
                  f'overwritten --> {p}')
            return p

    def get_prior_parameters(self):
        # prior parameters for a, b, Dc, mu0 (in that order)
        mus = [-5, -5, 4, -1]
        sigmas = [0.8, 0.8, 0.5, 0.3]

        return mus, sigmas

    def set_vch(self, vlps):
        vch = np.max(vlps)
        return vch

    def set_disp_bounds(self, x):
        self.mindisp = x[0]
        self.maxdisp = x[-1]


myglobals = Globals()
