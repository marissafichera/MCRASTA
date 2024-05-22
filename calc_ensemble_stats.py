import os
import sys
import arviz as az
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from gplot import gpl
import plot_mcmc_results as pmr
import psutil
from plotrsfmodel import rsf, staterelations
from multiprocessing import Process, Queue, Pool


# 1. read in .npy file
# 2. calculate log(p) for each simulation
# 3. calculate ensemble statistics
# 4. plot simulated mus

home = os.path.join(os.path.expanduser('~'), 'PycharmProjects', 'mcmcrsf_xfiles', 'mcmc_out')


# idata_location = gpl.make_path('mcmc_out', 'linux_runs_all', gpl.samplename, gpl.sim_name)


def manual_bci(x, mt, msims):
    # calculate probability distribution of simulated mus at each displacement
    hs = []
    for i in range(len(x)):
        h = plt.hist(msims[:, i], bins=100, range=[0, 1], density=True)
        hs.append(h)
    plt.show()


def get_npy_data(n, chunksize):
    print(f'reading dataset: {gpl.msname}_{n}.npy')
    filename = gpl.make_path('musim_out', f'{gpl.samplename}', f'{gpl.msname}_{n}.npy')
    alldata = np.load(filename)

    if chunksize is not None:
        return alldata[0:chunksize, :], alldata.shape[0]
    else:
        return alldata, alldata.shape[0]


def load_section_data():
    section_data = pd.read_csv(os.path.join(gpl.idata_location(), 'section_data.csv'))
    df = pd.DataFrame(section_data)
    times = df['times'].to_numpy().round(2)
    mutrue = df['mutrue'].to_numpy().round(3)
    vlps = df['vlps'].to_numpy().round(2)
    x = df['x'].to_numpy().round(2)

    return times, mutrue, vlps, x


def calc_combined_stats(col_sums, chunksize, num_chunks):
    # n1, n2, mean1, mean2, std1, std2):
    # n = chunksize * num_chunks

    means_combined = (np.nansum(col_sums, axis=0)) / (num_chunks * chunksize)
    # means_combined.reshape((1, len(means_combined)))
    means_combined = np.reshape(means_combined, (1, len(means_combined)))

    # means_combined = ((n * means1) + (n * means2)) / sum(n)

    # ds = (means - means_combined) ** 2
    # d2 = means2 - means_combined

    # stdevssq = stdevs ** 2

    # stdevs_combined = np.sqrt(n * (stdevssq.sum(axis=0) + ds.sum(axis=0)) / n)

    # stdevs_combined = np.sqrt((n1 * (stds1 ** 2)) + (n2 * (stds2 ** 2)) +
    #                           (n1 * (d1 ** 2)) + (n2 * (d2 ** 2)) / (n1 + n2))

    return means_combined


def calc_combined_stdev(s):
    return np.nansum(s, axis=0)


def calc_ensemble_stats(x, msims, ddof):
    msims[msims < 0] = np.nan
    msims[msims > 1] = np.nan
    msims[msims == np.inf] = np.nan
    msims[msims == -np.inf] = np.nan

    means = np.nanmean(msims, axis=0)
    # stdevs = np.nanstd(msims, axis=0, ddof=ddof)

    return means


def generate_rsf_data(inputs):
    gpl.read_from_json(gpl.idata_location())
    # print(f'self.threshold = {gpl.threshold}')
    a, b, Dc, mu0 = inputs

    # dimensional variables output from mcmc_rsf.py
    times, mutrue, vlps, x = load_section_data()
    k, vref = get_constants(vlps)
    lc, vmax = get_vmax_l0(vlps)

    mutrue.round(2).astype('float32')
    vlps.round(2).astype('float32')

    # time is the only variable that needs to be re-nondimensionalized...?
    k0, vlps0, vref0, t0 = nondimensionalize_parameters(vlps, vref, k, times, vmax)

    # set up rsf model
    model = rsf.Model()
    model.k = k  # Normalized System stiffness (friction/micron)
    model.v = vlps[0]  # Initial slider velocity, generally is vlp(t=0)
    model.vref = vref  # Reference velocity, generally vlp(t=0)

    state1 = staterelations.DieterichState()
    state1.vmax = vmax.astype('float32')
    state1.lc = gpl.lc

    model.state_relations = [state1]  # Which state relation we want to use

    model.time = np.round(t0, 2).astype('float32')

    # Set the model load point velocity, must be same shape as model.model_time
    model.loadpoint_velocity = vlps.astype('float32')

    model.mu0 = mu0
    model.a = a
    state1.b = b
    state1.Dc = Dc

    model.solve(threshold=gpl.threshold)

    mu_sim = model.results.friction.astype('float32')
    # state_sim = model.results.states

    resids = np.transpose(mutrue) - mu_sim
    rsq = resids ** 2
    srsq = np.nansum(rsq)
    logp = np.abs(- 1 / 2 * srsq)

    return logp


def plot_results(x, mt, means, stdevs, bestvars, bestmusim):
    abest, bbest, Dcbest, mu0best = bestvars
    sig_upper = means + stdevs
    sig_lower = means - stdevs

    plt.plot(x, np.transpose(means), color='indianred', label='ensemble mean')
    plt.plot(x, np.transpose(sig_lower), color='salmon', label='ensemble std. dev.')
    plt.plot(x, np.transpose(sig_upper), color='salmon')
    plt.ylim([np.min(sig_lower) - 0.1, np.max(sig_upper) + 0.1])

    print(f'a = {abest}; b = {bbest}; Dc = {Dcbest}; mu0 = {mu0best}')

    plt.gcf()
    plt.plot(x, mt, 'k.', label='observed', alpha=0.1)
    plt.plot(x, np.transpose(bestmusim), color='red', label='best fit')
    plt.xlabel('load point displacement ($\mu$m)')
    plt.ylabel('$\mu$')
    plt.title(f'Ensemble Statistics: {gpl.section_id}')
    plt.legend()

    # plt.show()


def write_best_estimates(bvars, lpbest):
    a, b, Dc, mu0 = bvars
    p = gpl.get_musim_storage_folder()
    fname = os.path.join(p, 'param_estimates_best.txt')

    paramstrings = ['a', 'b', 'Dc', 'mu0', 'lpbest']
    paramvals = [a, b, Dc, mu0, lpbest]

    with open(fname, mode='w') as f:
        for string, val in zip(paramstrings, paramvals):
            f.write(f'{string}: {val}\n')


def find_best_fits(x, mt, msims, a, b, Dc, mu0):
    resids = np.transpose(mt) - msims
    rsq = resids ** 2
    srsq = np.nansum(rsq, axis=1)
    logps = np.abs(- 1 / 2 * srsq)

    # plt.plot(logps, '.')
    # plt.ylim([-10, 0])
    # plt.show()

    sortedi = np.argsort(logps)

    ms_best = msims[sortedi[0], :]
    abest = a[sortedi[0]]
    bbest = b[sortedi[0]]
    Dcbest = Dc[sortedi[0]]
    mu0best = mu0[sortedi[0]]
    logpbest = logps[sortedi[0]]

    return [abest, bbest, Dcbest, mu0best], ms_best, logpbest


def get_model_values(idata):
    modelvals = az.extract(idata.posterior, combined=True)

    a = modelvals.a.values
    b = modelvals.b.values
    Dc = modelvals.Dc.values
    mu0 = modelvals.mu0.values

    return a, b, Dc, mu0


def draw_from_posteriors(idata, ndraws=1000):
    # draw values from the 89% credible interval for each parameter
    # then generate rsf data for draws

    a, b, Dc, mu0 = get_model_values(idata)

    adraws = np.random.choice(a, ndraws)
    bdraws = np.random.choice(b, ndraws)
    Dcdraws = np.random.choice(Dc, ndraws)
    mu0draws = np.random.choice(mu0, ndraws)

    return adraws, bdraws, Dcdraws, mu0draws


def calc_sums(msims):
    msims[msims < 0] = np.nan
    msims[msims > 1] = np.nan
    msims[msims == np.inf] = np.nan
    msims[msims == -np.inf] = np.nan

    column_sums = np.nansum(msims, axis=0)

    return column_sums


def save_stats(ens_mean, ens_stdev, bestfit):
    p = gpl.get_postprocess_storage_folder()
    np.save(os.path.join(p, 'ens_mean'), ens_mean)
    np.save(os.path.join(p, 'ens_stdev'), ens_stdev)
    np.save(os.path.join(p, 'bestfit'), bestfit)


def save_figs():
    # check if folder exists, make one if it doesn't
    name = gpl.get_musim_storage_folder()
    print(f'find figures and .out file here: {name}')
    w = plt.get_fignums()
    print('w = ', w)
    for i in plt.get_fignums():
        print('i = ', i)
        plt.figure(i).savefig(os.path.join(name, f'fig{i}.png'), dpi=300, bbox_inches='tight')


def main():


    num_file_subsets = 20
    num_chunks = 2000000 / 100000
    num_chunks = int(num_chunks)

    chunksize = 100000

    sums_each_column = np.empty((num_chunks, len(mutrue)))

    lpbest = 123456789
    start_idx = 0
    nc = 0
    process = psutil.Process()
    for num in np.arange(num_file_subsets):
        msims_file, total_sims_in_file = get_npy_data(num, chunksize=None)
        print(f'msims file size = {msims_file.shape}')
        print(total_sims_in_file)
        for j in range(0, total_sims_in_file, chunksize):
            end_idx = start_idx + chunksize
            print(f'starting index = {start_idx}')
            print(f'ending index = {end_idx}')
            print(f'j = {j}')
            msims = msims_file[j:j + chunksize, :]
            print(f'msims size = {msims.shape}')
            a, b, Dc, mu0 = get_model_values(idata, start_idx, end_idx)

            bestvars, ms_best, logpbest = find_best_fits(x, mutrue, msims, a, b, Dc, mu0)
            print(f'after running best fits: {process.memory_info().rss}')

            if logpbest < lpbest:
                lpbest = logpbest
                bvars = bestvars
                best_musim = ms_best

            sums_each_column[nc, :] = calc_sums(msims)
            print(f'after calc sums: {process.memory_info().rss}')

            start_idx = end_idx

            nc += 1
            print(process.memory_info().rss)
        del msims_file, msims

    combined_means = calc_combined_stats(sums_each_column, chunksize, num_chunks)

    sum_squares_each = np.empty((num_chunks, len(mutrue)))
    nc = 0
    for num in np.arange(num_file_subsets):
        msims_file, total_sims_in_file = get_npy_data(num, chunksize=None)
        print(msims_file.shape)
        print(combined_means.shape)
        for j in range(0, total_sims_in_file, chunksize):
            msims = msims_file[j:j + chunksize, :]
            msims[msims < 0] = np.nan
            msims[msims > 1] = np.nan
            msims[msims == np.inf] = np.nan
            msims[msims == -np.inf] = np.nan
            squareterm = (msims - combined_means) ** 2
            sum_squares_each[nc, :] = np.nansum(squareterm, axis=0)
            nc += 1

    sum_squares_all = np.nansum(sum_squares_each, axis=0)
    stdevs_all = 1 / np.sqrt(num_chunks * chunksize) * np.sqrt(sum_squares_all)

    plot_results(x, mutrue, combined_means, stdevs_all, bvars, best_musim)

    write_best_estimates(bvars, lpbest)

    save_stats(combined_means, stdevs_all, best_musim)
    save_figs()

    print('done')


if __name__ == '__main__':
    t, mutrue, vlps, x = load_section_data()
    idata = pmr.load_inference_data()
    parent_dir = gpl.get_musim_storage_folder()


    num_draws = 1000
    # a, b, Dc, mu0 = get_model_values(idata)
    drawed_vars = draw_from_posteriors(idata, num_draws)

    a, b, Dc, mu0 = drawed_vars

    a = np.round(a, 6).astype('float32')
    b = np.round(b, 6).astype('float32')
    Dc = np.round(Dc, 3).astype('float32')
    mu0 = np.round(mu0, 4).astype('float32')

    pathname = os.path.join(parent_dir, f'musim_randdraws_p{gpl.section_id}')

    with Pool(processes=20, maxtasksperchild=1) as pool:
        outputs = pool.map(generate_rsf_data, zip(a, b, Dc, mu0))
        op = np.array(outputs)
        np.save(pathname, op)

