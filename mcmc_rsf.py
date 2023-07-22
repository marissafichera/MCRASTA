import os
import numpy as np
import pymc as pm
import matplotlib.pyplot as plt
import arviz as az
import pandas as pd
from rsfmodel import staterelations, rsf, plot
import pytensor
import sys
import h5py
import scipy as sp
from scipy.signal import savgol_filter
from multiprocessing import process

global mutrue, times, vlps, lpdisp, fmcount, sim_name, dirpath

um_to_mm = 0.001

pytensor.config.optimizer = 'fast_compile'
rng = np.random.normal()
np.random.seed(1234)
az.style.use("arviz-darkgrid")


def calc_derivative(y, x, window_len=100):
    # returns dydx
    if window_len is not None:
        # smooth
        # x_smooth = smooth(x,window_len=params['window_len'],window='flat')
        # y_smooth = smooth(y,window_len=params['window_len'],window='flat')
        # dydx = np.gradient(y_smooth,x_smooth)
        dxdN = savgol_filter(x,
                             window_length=window_len,
                             polyorder=3,
                             deriv=1)
        dydN = savgol_filter(y,
                             window_length=window_len,
                             polyorder=3,
                             deriv=1)
        dydx = dydN / dxdN

        dydx_smooth = savgol_filter(dydx,
                                    window_length=window_len,
                                    polyorder=1)
        return dydx_smooth
    else:
        dydx = np.gradient(y, x)
        return dydx


def get_obs_data():
    homefolder = os.path.expanduser('~')
    path = os.path.join('PycharmProjects', 'mcmcrsf_xfiles', 'data', 'FORGE_DataShare', 'p5894')
    # path = r'PycharmProjects\mcmcrsf_xfiles\data\FORGE_DataShare\p5756'
    name = 'p5894_proc.hdf5'
    fullpath = os.path.join(homefolder, path, name)
    print(f'getting data from: {fullpath}')
    f = h5py.File(os.path.join(homefolder, path, name), 'r')
    print(list(f.keys()))

    df, names = read_hdf(fullpath)
    print(names)

    # preplot(df, names)
    # 'hdcdt_um': horizontal displacement in microns
    # 'hstress_mpa': the horizontal (normal) stress in MPa
    # 'laythick_um': the layer thickness for a single fault in microns
    # 'mu': the friction calculated for the material (shear stress / effective normal stress)
    # 'recnum': the record number of collected data,
    # 'sampfreq_hz': the sampling frequency used during the experiment
    # 'sstrain': the shear strain for a single fault
    # 'sync': the sync pulse used to align mechanical and acoustic data
    # 'time_s': the time during the experiment in seconds
    # 'vdcdt_um':  the vertical (shear) displacement in microns,
    # 'vstress_mpa': the vertical (shear) stress in MPa

    # first remove any mu < 0 data from end of experiment
    idx = np.argmax(df['mu'] < 0)
    df = df.iloc[0:idx]

    t = df['time_s'].to_numpy()
    mu = df['mu'].to_numpy()
    x = df['vdcdt_um'].to_numpy()

    vlps = calc_derivative(x, t)

    f_ds = downsample_dataset(mu, t, vlps, x)

    sectioned_data = section_data(f_ds)

    print(f'sectioned data shape = {sectioned_data.shape}')

    t = sectioned_data[:, 1]

    print('is time series monotonic after processing??')
    print(isMonotonic(t))

    cleaned_data = remove_non_monotonic(t, sectioned_data, axis=0)

    mutrue = cleaned_data[:, 0]
    times = cleaned_data[:, 1]
    vlps = cleaned_data[:, 2]
    x = cleaned_data[:, 3]

    # plt.figure(1)
    # plt.plot(times, vlps)
    # plt.xlabel('time (s)')
    #
    # plt.figure(2)
    # plt.plot(x*um_to_mm, mutrue)
    # plt.xlabel('displacement (mm)')
    # plt.ylabel('mu')
    # plt.show()

    return mutrue, times, vlps, x


def read_hdf(fullpath):
    filename = fullpath
    print(f'reading file: {filename}')
    names = []
    df = pd.DataFrame()
    with h5py.File(filename, 'r') as f:
        # Print all root level object names (aka keys)
        # these can be group or dataset names
        print("Keys: %s" % f.keys())
        # get first object name/key; may or may NOT be a group
        a_group_key = list(f.keys())[0]

        # loop on names:
        for name in f.keys():
            print(name)
            names.append(name)
        # loop on names and H5 objects:
        for name, h5obj in f.items():
            if isinstance(h5obj, h5py.Group):
                print(f'{name} is a Group')
            elif isinstance(h5obj, h5py.Dataset):
                print(f'{name} is a Dataset')
                # return a np.array using dataset object:
                arr1 = h5obj[:]
                print(type(arr1))
                # return a np.array using dataset name:
                arr2 = f[name][:]
                # compare arr1 to arr2 (should always return True):
                print(np.array_equal(arr1, arr2))
                df[f'{name}'] = arr1

    print('df = ', df)

    return df, names


def preplot(df, colnames):
    t = df['time_s']

    plt.plot(t, df['mu'])
    plt.title('mu')
    plt.xlabel('time (s)')

    plt.figure(2)
    plt.plot(t, df['vdcdt_um'])
    plt.title('displacement')

    # for i, col in enumerate(colnames):
    #     plt.figure(i)
    #     plt.plot(t, df[f'{col}'])
    #     plt.title(f'{col}')
    #     plt.xlabel('time (s)')
    #
    # lpdisp = df['vdcdt_um']*um_to_mm
    # plt.figure(i+1)
    # plt.plot(lpdisp, df['mu'])
    # plt.show()


def downsample_dataset(mu, t, vlps, x):
    # low pass filter - come back and see what 1000 is and if mode should change
    mu_f = savgol_filter(mu, 50, 2, mode='mirror')
    print(f'mu_f.shape = {mu_f.shape}')

    # stack time and mu arrays to sample together
    f_data = np.column_stack((mu_f, t, vlps, x))
    print(f't_muf.shape = {f_data.shape}')

    # downsamples to every qth sample after applying low-pass filter along columns
    q = 10
    f_ds = sp.signal.decimate(f_data, q, ftype='fir', axis=0)
    print(f'number samples in downsampled series = {f_ds.shape}')
    t_ds = f_ds[:, 1]
    mu_ds = f_ds[:, 0]
    x_ds = f_ds[:, 3]

    # plot series as sanity check
    # plt.plot(x, mu, '.-', label='original data')
    # plt.plot(x, mu_f, '.-', label='filtered data')
    # plt.plot(x_ds, mu_ds, '.-', label='downsampled data')
    # plt.xlabel('disp (mm)')
    # plt.ylabel('mu')
    # plt.legend()
    # # plt.show()

    return f_ds


def section_data(data):
    df0 = pd.DataFrame(data)
    print(f'dataframe col names = {list(df0)}')
    df = df0.set_axis(['mu', 't', 'vlps', 'x'], axis=1)
    print(f'new dataframe col names = {list(df)}')

    start_idx = np.argmax(df['x'] > 18 / um_to_mm)
    end_idx = np.argmax(df['x'] > 20 / um_to_mm)

    df_section = df.iloc[start_idx:end_idx]

    print(f'original shape = {df.shape}')
    print(f'section shape = {df_section.shape}')

    return df_section.to_numpy()


def generate_rsf_data(times, vlps):
    # runs rsfmodel.py to generate synthetic friction data
    a = 0.1
    b = 0.13
    Dc = 13
    mu0_t = 0.814
    vref = 1
    k = 0.03
    print('STARTING SYNTHETIC PARAMETERS - ANSWERS')
    print(f'a={a}')
    print(f'b={b}')
    print(f'Dc={Dc}')
    print(f'mu0={mu0_t}')

    # Size of dataset
    size = len(times)
    print(f'size of dataset = {size}')

    model = rsf.Model()

    # Set model initial conditions
    model.mu0 = mu0_t  # Friction initial (at the reference velocity)
    model.a = a  # Empirical coefficient for the direct effect
    model.k = k  # Normalized System stiffness (friction/micron)
    model.v = vlps[0]  # Initial slider velocity, generally is vlp(t=0)
    model.vref = vref  # Reference velocity, generally vlp(t=0)

    state1 = staterelations.DieterichState()
    state1.b = b  # Empirical coefficient for the evolution effect
    state1.Dc = Dc  # Critical slip distance

    model.state_relations = [state1]  # Which state relation we want to use

    # We want to solve for 40 seconds at 100Hz
    model.time = times

    # Set the model load point velocity, must be same shape as model.model_time
    model.loadpoint_velocity = vlps

    # Run the model!
    model.solve()

    mu = model.results.friction
    theta = model.results.states

    print(model.results)

    # plus noise
    mutrue = mu + (1 / 100) * np.random.normal(np.mean(mu), 0.1, (len(mu),))

    # change model results to noisy result, so I can still use the plots easily
    model.results.friction = mutrue

    thetatrue = theta

    # plt.figure(100)
    # plot.dispPlot(model)
    #
    # plt.figure(101)
    # plot.timePlot(model)
    # 
    # plt.figure(102)
    # plt.hist(mutrue_mincon)
    # plt.show()

    return mutrue, thetatrue, size


def mcmc_rsf_sim(rng, a, b, Dc, mu0, size=None):
    global times, vlps, lpdisp, fmcount
    t = times
    k, vref = get_constants(vlps)

    # Simulate outcome variable
    model = rsf.Model()

    # Size of dataset
    model.datalen = len(t)
    print(model.datalen)

    # model.create_h5py_dataset()

    # Set model initial conditions
    model.mu0 = mu0  # Friction initial (at the reference velocity)
    model.a = a  # Empirical coefficient for the direct effect
    model.k = k  # Normalized System stiffness (friction/micron)
    model.v = vlps[0]  # Initial slider velocity, generally is vlp(t=0)
    model.vref = vref  # Reference velocity, generally vlp(t=0)

    state1 = staterelations.DieterichState()
    state1.b = b  # Empirical coefficient for the evolution effect
    state1.Dc = Dc  # Critical slip distance

    model.state_relations = [state1]  # Which state relation we want to use

    model.time = t

    lp_velocity = vlps

    # Set the model load point velocity, must be same shape as model.model_time
    model.loadpoint_velocity = lp_velocity
    model.loadpoint_displacement = lpdisp

    # Run the model!
    fmcount += 1
    model.count += 1
    print(f'FWD MODEL RUN COUNT ===== {fmcount}')
    model.solve()

    mu_sim = model.results.friction
    t_sim = model.results.time

    # print('process id == ', os.getpid())

    # plt.figure(100)
    # plot.dispPlot(model)

    # plot_rsfmodel_plots(mu_sim, t_sim)

    print('returning simulated mu vals')
    return mu_sim


def plot_rsfmodel_plots(musim, t):
    plt.figure(1000)
    plt.plot(t, musim)
    plt.plot(t, mutrue, 'k.')
    plt.xlabel('time')
    plt.ylabel('mu')
    plt.title('simulated')

    # plt.show(block=False)


def get_time(name):
    from datetime import datetime
    import time

    now = datetime.now()

    current_time = now.strftime("%H:%M:%S")
    print(f'{name} time = {current_time}')

    codetime = time.time()

    return codetime


def post_processing(idata, mutrue, times, vlps):
    # to extract model parameters being estimated
    modelsim_params = az.extract(idata.posterior)

    print(f'model params = {modelsim_params}')

    # to extract simulated mu values for realizations
    stacked_pp = az.extract(idata.posterior_predictive)
    print(f'stacked = {stacked_pp}')
    musims = stacked_pp.simulator.values
    df_musims = pd.DataFrame(musims)
    df_musims.to_csv(os.path.join(root, 'musims.csv'))

    print(f'simulated mu values = {musims}')
    print(f'shape of posterior predictive dataset = {musims.shape}')

    # plot trace and then posterior predictive plot
    plot_trace(idata)
    plot_posterior_predictive(idata)

    # now plot simulated mus with true mu
    t = times
    plt.figure(500)
    plt.plot(t, mutrue, 'k.', label='observed')
    plt.plot(t, musims, 'b-', alpha=0.3)
    plt.xlabel('time (s)')
    plt.ylabel('mu')
    plt.title('Observed and simulated friction values')
    plt.legend()

    print('post processing complete')


def get_constants(vlps):
    k = 0.0015
    vref = vlps[0]

    return k, vref


def get_priors():
    # a = pm.Normal('a', mu=0.006692, sigma=0.1)
    # b = pm.Normal('b', mu=0.00617, sigma=0.1)
    # Dc = pm.Normal('Dc', mu=61.8, sigma=20)
    # mu0 = pm.Normal('mu0', mu=0.44, sigma=0.1)

    a = pm.Uniform('a', lower=0.006 - 0.008, upper=0.007 + 0.008)
    b = pm.Uniform('b', lower=0.0059 - 0.008, upper=0.00617 + 0.008)
    Dc = pm.Uniform('Dc', lower=61.8 - 20, upper=61.8 + 20)
    mu0 = pm.Uniform('mu0', lower=0.44 - 0.1, upper=0.44 + 0.1)

    priors = [a, b, Dc, mu0]

    return priors


def save_figs(out_folder):
    # check if folder exists, make one if it doesn't
    name = out_folder
    print(f'folder name for fig saving = {name}')
    w = plt.get_fignums()
    print('w = ', w)
    for i in plt.get_fignums():
        print('i = ', i)
        plt.figure(i).savefig(os.path.join(name, f'fig{i}.png'), dpi=300)


def check_file_exist(folder, name):
    isExisting = os.path.exists(os.path.join(folder, name))
    if isExisting is False:
        print(f'file does not exist, returning file name --> {name}')
        return name
    elif isExisting is True:
        print(f'file does exist, rename new output for now, eventually delete previous --> {name}')
        oldname = name
        newname = f'{oldname}_a'
        return newname


def get_storage_folder(dirname):
    global dirpath

    print('checking if storage directory exists')
    homefolder = os.path.expanduser('~')
    outfolder = os.path.join('PycharmProjects', 'mcmcrsf_xfiles', 'mcmc_out')
    # name = sim_name

    dirpath = os.path.join(homefolder, outfolder, dirname)
    isExisting = os.path.exists(dirpath)
    if isExisting is False:
        print(f'directory does not exist, creating new directory --> {dirpath}')
        os.makedirs(dirpath)
        return dirpath
    elif isExisting is True:
        print(f'directory exists, all outputs will be saved to existing directory and any existing files will be '
              f'overwritten --> {dirpath}')
        return dirpath


def get_sim_name(draws, chains):
    global sim_name
    sim_name = f'out_{draws}d{chains}ch_lowerthreshtest'
    return sim_name


# def write_model_info(sim_name, smc_info, runtime, params_priors, constants, results_summary):
#     get_storage_folder(sim_name)
#     lines = sim_name, smc_info, runtime, params_priors, constants, results_summary
#     labels = 'sim_name', 'smc_info', 'runtime', 'params', 'constants', 'results'
#     strings = []
#     for line in lines:
#         string = line.astype(str)
#         value = f'{line}'
#
#
#     with open('simulation_summary.txt', 'w') as f:
#         f.writelines(strings)


def isMonotonic(A):
    return (all(A[i] <= A[i + 1] for i in range(len(A) - 1)) or
            all(A[i] >= A[i + 1] for i in range(len(A) - 1)))


def remove_non_monotonic(times, data, axis=0):
    if not np.all(np.diff(times) >= 0):
        print('time series can become non-monotonic after downsampling which is an issue for the sampler')
        print('now removing non-monotonic t and mu values from dataset')
        print(f'input downsampled data shape = {data.shape}')
        # Find the indices where the array is not monotonically increasing
        non_monotonic_indices = np.where(np.diff(times) < 0)[0]
        print(f'non monotonic time indices = {non_monotonic_indices}')

        # Remove the non-monotonic data points
        cleaned_data = np.delete(data, non_monotonic_indices, axis)
        print('removed bad data? should be True')
        print(isMonotonic(cleaned_data[:, 1]))
        return cleaned_data

    # Array is already monotonically increasing, return it as is
    print('Array is already monotonically increasing, returning as is')
    return data


def sample_posterior_predcheck(idata):
    pm.sample_posterior_predictive(idata, extend_inferencedata=True)

    # save trace for easier debugging if needed
    # out_name = f'{sim_name}_idata'
    # folder = get_storage_folder(dirname='idata')
    # name = check_file_exist(folder, out_name)
    # idata.to_netcdf(os.path.join(folder, f'{name}'))


def plot_trace(idata):
    plt.figure(400)
    az.plot_trace(idata, var_names=['a', 'b', 'Dc', 'mu0'], kind="rank_vlines")


def plot_posterior_predictive(idata):
    az.plot_ppc(idata)


def save_stats(idata, root):
    summary = az.summary(idata, kind='stats')
    print(f'summary: {summary}')
    summary.to_csv(os.path.join(root, 'idata.csv'))


def main():
    print('MCMC RATE AND STATE FRICTION MODEL')

    # observed data
    global mutrue, times, vlps, lpdisp
    mutrue, times, vlps, lpdisp = get_obs_data()

    # so I can figure out how long it's taking when I inevitably forget to check
    comptime_start = get_time('start')

    # generate synthetic data
    # times, vlps = get_times_vlps()
    # mutrue, tht, datalen = generate_rsf_data(times, vlps)

    # define smc model parameters
    with pm.Model() as mcmcmodel:
        global fmcount

        # priors on stochastic parameters, constants
        priors = get_priors()
        a, b, Dc, mu0 = priors
        k, vref = get_constants(vlps)

        fmcount = 0
        # likelihood function
        simulator = pm.Simulator('simulator', mcmc_rsf_sim, params=(a, b, Dc, mu0), epsilon=0.01,
                                 observed=mutrue)

        # seq. mcmc sampler parameters
        draws = 10
        # THESE ARE NOT MARKOV CHAINS
        chains_for_convergence = 2
        # more cores for the markov chain spawns?? doesn't work but maybe manually could do it
        cores = 39
        print(f'num draws = {draws}; num chains = {chains_for_convergence}')

        # MUST BE SAMPLE SMC IF USING SIMULATOR FOR LIKELIHOOD FUNCTION
        kernel_kwargs = dict(correlation_threshold=0.5)
        idata = pm.sample_smc(draws=draws, kernel=pm.smc.kernels.MH, chains=chains_for_convergence, cores=cores,
                              **kernel_kwargs)
        get_sim_name(draws, chains_for_convergence)

        get_storage_folder(sim_name)

        print(f'inference data = {idata}')

        # save model parameter stats
        save_stats(idata, dirpath)

        # sample the posterior for validation
        sample_posterior_predcheck(idata)

        # print and save new idata stats that includes posterior predictive check
        summary_pp = az.summary(idata, kind='stats')
        print(f'idata summary: {summary_pp}')
        save_stats(idata, dirpath)

        # post-processing takes results and makes plots, save figs saves figures
        post_processing(idata, mutrue, times, vlps)
        save_figs(dirpath)

    comptime_end = get_time('end')
    time_elapsed = comptime_end - comptime_start
    print(f'time elapsed = {time_elapsed}')

    # write simulation info to text file
    sim_smc_info = [draws, chains_for_convergence, cores]
    sim_runtime = time_elapsed
    sim_params_priors = priors
    sim_constants = k, vref
    # sim_results_summary = summary

    # write_model_info(sim_name, sim_smc_info, sim_runtime, sim_params_priors, sim_constants, sim_results_summary)

    plt.show()

    print('simulation complete')


if __name__ == '__main__':
    main()
