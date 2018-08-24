import sys, os, time, random, click, logging, shutil
import numpy as np
import pickle
from pprint import pprint
from copy import deepcopy

from scipy.optimize import minimize
from scipy.optimize import basinhopping

from mpi4py import MPI
import h5py
from neuroh5.io import append_cell_attributes, read_population_ranges, read_cell_attributes
import dentate
from dentate.env import Env
import dentate.utils as utils
from dentate.utils import list_find, list_argsort, get_script_logger
from dentate.stimulus import generate_spatial_offsets

script_name = 'generate_DG_PP_features_reduced_h5support.py'

io_size=-1
chunk_size=1000
value_chunk_size=1000

field_width_params = [35.0, 0.32]
field_width = lambda x : 40. + field_width_params[0] * (np.exp(x / field_width_params[1]) - 1.)
max_field_width = field_width(1.)

feature_grid = 0
feature_place_field = 1

N_MPP = 38000
N_MPP_GRID = int(N_MPP * 0.7)
N_MPP_PLACE = N_MPP - N_MPP_GRID

N_LPP = 1300 #int(N_MPP * 1.10)
N_LPP_PLACE = N_LPP 
N_LPP_GRID = 0

arena_dimension = 100.
init_scale_factor = 10.0
init_orientation_jitter = [-10., 10.] #[np.deg2rad(-10.), np.deg2rad(10.)]
init_lambda_jitter = [-10., 10.]
resolution = 5.
nmodules = 10
modules = np.arange(nmodules)

param_list, cost_evals = [], []
nplace_fields = []

def dcheck(x,y,xi,yi,spacing):
    radius = spacing / 2.
    distances = np.sqrt( (x - xi) ** 2 + (y - yi) ** 2)
    mask = np.zeros(x.shape)
    mask[distances < radius] = 1
    return mask

def place_fill_map(xp, yp, spacing, orientation, xf, yf):

    nx, ny = xp.shape
    rate_map = np.zeros((nx, ny))
    rate_map = get_rate(xp,yp, spacing, orientation, xf, yf, ctype='place')
    return rate_map


def grid_fill_map(xp, yp, spacing, orientation, xf, yf):

    nx, ny = xp.shape
    rate_map = np.zeros((nx, ny))
    rate_map = get_rate(xp, yp, spacing, orientation, xf, yf, ctype='grid')
    return rate_map

def get_rate(x, y, grid_spacing, orientation, x_offset, y_offset,ctype='grid'):
    mask = None
    if ctype == 'place':
         mask = dcheck(x,y,x_offset, y_offset, grid_spacing)
    theta_k = [np.deg2rad(-30.), np.deg2rad(30.), np.deg2rad(90.)]
    inner_sum = np.zeros(x.shape)
    for k in range(len(theta_k)):
        inner_sum += np.cos( ((4 * np.pi) / (np.sqrt(3)*grid_spacing)) * (np.cos(theta_k[k]) * (x - x_offset) + (np.sin(theta_k[k]) * (y - y_offset))))
    rate_map = transfer(inner_sum)
    if mask is not None:
        return rate_map * mask
    return rate_map

def transfer(z, a=0.3, b=-1.5):
    return np.exp(a*(z-b)) - 1 


def to_file(rate_map, fn, module=1):
    nx, ny = rate_map.shape
    f = open(fn, 'w')
    for i in range(nx):
        for j in range(ny):
            f.write(str(rate_map[i,j]) + '\t')
        f.write('\n')

def generate_mesh(scale_factor=init_scale_factor):

    mega_arena_x_bounds = [-arena_dimension * scale_factor/2., arena_dimension * scale_factor/2.]
    mega_arena_y_bounds = [-arena_dimension * scale_factor/2., arena_dimension * scale_factor/2.]
    mega_arena_x = np.arange(mega_arena_x_bounds[0], mega_arena_x_bounds[1], resolution)
    mega_arena_y = np.arange(mega_arena_y_bounds[0], mega_arena_y_bounds[1], resolution)
    return np.meshgrid(mega_arena_x, mega_arena_y, indexing='ij')

def rate_histogram(features_dict, xp, yp, xoi, yoi, ctype='grid', module=0):
    r = []
    for idx in features_dict.keys():
        cell = features_dict[idx]
        if cell['Module'][0] == module:       
            spacing, orientation = None, 0.0
            if cell.has_key('Grid Spacing'):
                spacing = cell['Grid Spacing']
                orientation = cell['Grid Orientation']
            else:
                spacing = cell['Field Width']
            x_offset, y_offset = cell['X Offset'], cell['Y Offset']
            rate = get_rate_2(np.array([xp[xoi,yoi]]), np.array([yp[xoi,yoi]]), spacing, orientation, x_offset, y_offset,ctype=ctype)
            r.append(rate[0])
    return np.asarray(r).reshape(-1,)


def make_hist(features_dict, xp, yp, population='MPP',ctype='grid',modules=[0],xoi=0, yoi=0):
    for module in modules:
        rate = rate_histogram(features_dict, xp, yp, xoi, yoi, module=module,ctype=ctype)
        fn = population+'/'+ctype+'-module-'+str(module)+'-rates-x-'+str(xoi)+'-y-'+str(yoi)+'.txt'
        list_to_file(fn, rate)

def make_hist_2(rmap, population='MPP', ctype='grid',modules=[0],xoi=0,yoi=0):
    for module in modules:
        rmatrix = rmap[module]
        rates = rmatrix[xoi,yoi,:]
        fn = population+'/'+ctype+'-module-'+str(module)+'-rates-x-'+str(xoi)+'-y-'+str(yoi)+'.txt'
        list_to_file(fn, rates)
    
def list_to_file(fn, r):
    f = open(fn, 'w')
    for v in r:
        f.write(str(v)+'\t')
    f.write('\n')
    f.close()    

def peak_to_trough(module_cells, modules=modules):
    minmax_evaluations = np.asarray([1.0 for _ in np.arange(nmodules)],dtype='float32')
    mean_evaluations = np.asarray([1.0 for _ in np.arange(nmodules)], dtype='float32')
    var_evaluations = np.asarray([1.0 for _ in np.arange(nmodules)], dtype='float32')

    for mod in module_cells.keys():
        cells = module_cells[mod]
        module_rate_map = []
        for (c,cell) in enumerate(cells):
            nx, ny = cell['Nx'][0], cell['Ny'][0]
            rate_map = cell['Rate Map'].reshape(nx, ny)
            module_rate_map.append(rate_map)
        summed_map = np.sum(module_rate_map,axis=0)
        variance_map = np.var(module_rate_map,axis=0)
        
        minmax_evaluations[mod] = np.divide(float(np.max(summed_map)), float(np.min(summed_map)))
        var_evaluations[mod] = np.divide(float(np.max(variance_map)), float(np.min(variance_map)))
                

    return minmax_evaluations - 1., mean_evaluations - 1., var_evaluations - 1.

def fraction_active(module_cells, modules=modules, target=0.30):
    rates = {mod:[] for mod in modules}
    for mod in module_cells.keys():
        cells = module_cells[mod]
        for cell in cells:
            nx, ny = cell['Nx'][0], cell['Ny'][0]
            rate_map = cell['Rate Map'].reshape(nx, ny)
            rates[mod].append(rate_map)
    nxx, nyy = np.meshgrid(np.arange(nx), np.arange(ny))
    coords = zip(nxx.reshape(-1,), nyy.reshape(-1,))
    frac_active_dict = {(i,j): {k:None for k in modules} for (i,j) in coords}
    diagonal_positions = [ (i,j) for (i,j) in frac_active_dict.keys()]
    for (px, py) in diagonal_positions:
        for key in rates.keys():
            module_maps = np.asarray(rates[key])
            position_rates = module_maps[:,px,py]
            frac_active = calculate_fraction_active(position_rates)
            frac_active_dict[(px,py)][key] = frac_active
    target_fraction_active = {(i,j): {k: target for k in modules} for (i,j) in frac_active_dict.keys()}
    diff_fraction_active = {(i,j): {k: np.abs(target_fraction_active[(i,j)][k]-frac_active_dict[(i,j)][k]) for k in modules} for (i,j) in frac_active_dict.keys()}
    
    module_error = [ [] for _ in range(len(modules))]
    for (i,j) in diff_fraction_active.keys():
        pos_errors = diff_fraction_active[(i,j)]
        for module in pos_errors.keys():
            mod_e = pos_errors[module]
            module_error[module].append(mod_e)
    module_error = np.asarray(module_error, dtype='float32')
    module_mean = np.array([ 0.0 for _ in range(len(modules))])
    module_var = np.array([ 0.0 for _ in range(len(modules))])

    for i in range(len(module_error)):
        module_mean[i] = np.mean(module_error[i])
        module_var[i] = np.var(module_error[i])
    return module_mean, module_var


def calculate_fraction_active(rates, threshold=0.1):
    max_rate = np.max(rates)
    normalized_rates = np.divide(rates, max_rate)
    num_active = len(np.where(normalized_rates > threshold)[0])
    fraction_active = np.divide(float(num_active), len(normalized_rates))
    return fraction_active               
            
def cost_prepare_grid(x, cell_modules, mesh):
    sf = x
    xp, yp = mesh
    for mod in cell_modules.keys():
        cells = cell_modules[mod]
        for (c,cell) in enumerate(cells):
            orientation, spacing = cell['Jittered Grid Orientation'], cell['Jittered Grid Spacing']
            xf, yf = cell['X Offset'][0], cell['Y Offset'][0]
            xf_scaled, yf_scaled = xf * sf[mod], yf * sf[mod]
            cell['X Offset Scaled'] = np.array([xf_scaled], dtype='float32')
            cell['Y Offset Scaled'] = np.array([yf_scaled], dtype='float32')
            rate_map = grid_fill_map(xp, yp, spacing, orientation, xf_scaled, yf_scaled)
            nx, ny = rate_map.shape
            cell['Rate Map'] = rate_map.reshape(-1,).astype('float32')
            cell['Nx'] = np.array([nx], dtype='int32')
            cell['Ny'] = np.array([ny], dtype='int32')

def cost_prepare_place(x, cell_modules, mesh):
    sf = x
    xp, yp = mesh
    for mod in cell_modules.keys():
        cells = cell_modules[mod]
        for (c, cell) in enumerate(cells):
            nfields = cell['Num Fields'][0]
            place_width = cell['Field Width']
            place_orientation = 0.0
            xf, yf = cell['X Offset'], cell['Y Offset']
            scale = sf[mod]
            xf_scaled, yf_scaled = xf * scale, yf * scale
            cell['X Offset Scaled'] = np.asarray(xf_scaled, dtype='float32')
            cell['Y Offset Scaled'] = np.asarray(yf_scaled, dtype='float32')
            rate_map = np.zeros((xp.shape[0], xp.shape[1]))
            for n in range(nfields):
                rate_map += place_fill_map(xp, yp, place_width[n], place_orientation, xf_scaled[n], yf_scaled[n])
            nx, ny = rate_map.shape
            cell['Rate Map'] = rate_map.reshape(-1,).astype('float32')
            cell['Nx'] = np.array([nx], dtype='int32')
            cell['Ny'] = np.array([ny], dtype='int32')

def module_merge(x, y):
    return {k: x[k] + y[k] for k in x.keys()}
        
def translate_cells(cell_modules, x_translate, y_translate, scale_factors):
    for mod in cell_modules.keys():
        cells = cell_modules[mod] 
        curr_xt = x_translate[mod]
        curr_yt = y_translate[mod] 
        for cell in cells:
            xf, yf = cell['X Offset'] + curr_xt, cell['Y Offset'] + curr_yt
            cell['X Offset'] = np.asarray(xf, dtype='float32')
            cell['Y Offset'] = np.asarray(yf, dtype='float32')
           
            xf_scaled, yf_scaled = xf * scale_factors[mod], yf * scale_factors[mod]
            cell['X Offset Scaled'] = np.asarray(xf_scaled, dtype='float32')
            cell['Y Offset Scaled'] = np.asarray(yf_scaled, dtype='float32')

def cost_func(x, grid, place, mesh, centroid, rank):
    param_list.append(x)
    if centroid:
        cell_modules = module_merge(grid, place)
        prev_x_centroids, prev_y_centroids = calculate_module_centroids(cell_modules)
        curr_x_centroids, curr_y_centroids = x[nmodules:2*nmodules], x[2*nmodules:3*nmodules]
        x_translate = [curr_x_centroids[i] - prev_x_centroids[i] for i in range(len(prev_x_centroids))]
        y_translate = [curr_y_centroids[i] - prev_y_centroids[i] for i in range(len(prev_y_centroids))]
        if not(all(x == 0.0 for x in x_translate) and all(y == 0.0 for y in y_translate)):
            translate_cells(grid, x_translate, y_translate, x[0:nmodules])
            translate_cells(place, x_translate, y_translate, x[0:nmodules])

    cost_prepare_grid(x[0:nmodules], grid, mesh)
    cost_prepare_place(x[0:nmodules], place, mesh)
    cell_modules = module_merge(grid, place)
    if rank == 0:
        tic = time.time()
    minmax_ratio_evaluations, mean_ratio_evaluations, var_ratio_evaluations = peak_to_trough(cell_modules, modules=modules)
    minmax_ratio_sum = np.sum(minmax_ratio_evaluations)
    mean_ratio_sum = np.sum(mean_ratio_evaluations)
    var_ratio_sum = np.sum(var_ratio_evaluations)
    cost_peak_trough = (minmax_ratio_sum ** 2 + mean_ratio_sum ** 2 + var_ratio_sum ** 2)
 
    fraction_active_mean_evaluation, fraction_active_var_evaluation = fraction_active(cell_modules, modules=modules)
    frac_active_mean_cost = np.sum(fraction_active_mean_evaluation)
    frac_active_var_cost = np.sum(fraction_active_var_evaluation)
    cost_frac_active = frac_active_mean_cost ** 2 + frac_active_var_cost ** 2

    total_cost = 0.5 * (cost_peak_trough + cost_frac_active)
    cost_evals.append(total_cost)
    if rank == 0:
        elapsed = time.time() - tic
    else:
        elapsed = 0.0
    print('Cost: %f calculted in %f seconds' % (total_cost,elapsed))
    print('Fraction active contribution: %f' % cost_frac_active)
    print('Peak-trough contribution: (%f,%f,%f)' % (minmax_ratio_sum ** 2, mean_ratio_sum ** 2, var_ratio_sum ** 2))
    print(x)
    print('---------------------')
    return total_cost

class OptimizationRoutine(object):
    def __init__(self, comm, grid, place, mesh, lbound, ubound):
        self.comm = comm
        self.grid = grid
        self.place = place
        self.mesh = mesh
        self.lbound = lbound
        self.ubound = ubound

    def optimize(self, x0, centroid=False, bounds=None, verbose=False):
        if bounds is None:
            bounds = [(lbound, ubound) for _ in x0]
        fnc = lambda x: cost_func(x, self.grid, self.place, self.mesh, centroid, self.comm.Get_rank())
        minimizer_kwargs = dict(method='L-BFGS-B', bounds=bounds, options={'disp':True,'eps':2.0, 'maxiter':3, 'ftol':1.0e-2})
        bh_output = basinhopping(fnc, x0, minimizer_kwargs=minimizer_kwargs, stepsize=10.0, T=2.0,disp=True, niter=3)

        if verbose:
            print(x0)
            print(bh_output.x)
            print(fnc(x0))
            print(fnc(bh_output.x))
        return bh_output.x, np.asarray(param_list, dtype='float32'), np.asarray(cost_evals, dtype='float32')

class Cell_Population(object):
    def __init__(self, comm, types_path, jitter_orientation=True, jitter_spacing=True, seed=64):
        self.comm = comm
        self.seed = seed
        self.types_path = types_path
        self.jitter_orientation = jitter_orientation
        self.jitter_spacing = jitter_spacing
        self.xp, self.yp = generate_mesh(scale_factor=1.0)

        self.local_random = random.Random()
        self.local_random.seed(self.seed - 1)
        self.feature_type_random = np.random.RandomState(self.seed - 1)
        self.place_field_random = np.random.RandomState(self.seed - 1)
        self.total_offsets = 0

        self.mpp_grid  =  None
        self.mpp_place =  None
        self.lpp_grid  =  None
        self.lpp_place =  None

        self.population_ranges = read_population_ranges(self.types_path, self.comm)[0]

    def full_init(self, scale_factors=1.0*np.ones(nmodules), full_map=False):
        self.initialize_cells(population='MPP')
        self.initialize_cells(population='LPP')
        self.generate_xy_offsets()

    def initialize_cells(self, population='MPP'):
        self.population_start, self.population_count = self.population_ranges[population]
        grid_orientation = [self.local_random.uniform(0., np.pi/3.) for i in range(nmodules)]
        feature_type_values = np.asarray([0, 1])
        if population == 'MPP':
            NCELLS = N_MPP
            feature_type_probs = np.asarray([0.3, 0.7])
        elif population == 'LPP':
            NCELLS = N_LPP
            feature_type_probs = np.asarray([0.0, 1.0])
        feature_types = self.feature_type_random.choice(feature_type_values,p=feature_type_probs, size=(NCELLS,))

        if population == 'MPP':
            self.mpp_grid, self.mpp_place = self._build_cells(NCELLS, population, feature_types, grid_orientation)
        elif population == 'LPP':
            self.lpp_grid, self.lpp_place = self._build_cells(NCELLS, population, feature_types, grid_orientation)

    def _build_cells(self, N, pop, feature_types, grid_orientation):
        grid_feature_dict, place_feature_dict = {}, {}

        nfield_probabilities = np.asarray([0.8, 0.15, 0.05])
        field_set = np.asarray([1,2,3])
        for i in range(N):
            gid = self.population_start + i
            self.local_random.seed(gid + self.seed)
            feature_type = feature_types[i]
            if feature_type == 0: # Grid cell
                this_module = self.local_random.choice(modules)
                orientation = grid_orientation[this_module]
                spacing = field_width(float(this_module)/float(np.max(modules)))
                grid_feature_dict[gid] = self._build_grid_cell(gid, orientation, spacing, this_module)
                self.total_offsets += 1
            elif feature_type == 1:
                nfields = self.place_field_random.choice(field_set, p=nfield_probabilities, size=(1,))
                self.total_offsets += nfields[0]
                this_module = self.local_random.choice(modules)
                cell_field_width = []
                for n in range(nfields[0]):
                    cell_field_width.append(field_width(self.local_random.random()))
                place_feature_dict[gid] = self._build_place_cell(gid, cell_field_width, this_module)
        return grid_feature_dict, place_feature_dict

    def _build_place_cell(self, gid, cell_field_width, module):

        self.place_field_random.seed(gid + self.seed)
        cell = {}
        cell['Num Fields'] = np.array([len(cell_field_width)], dtype='uint8')
        nplace_fields.append(len(cell_field_width))
        cell['gid'] = np.array([gid], dtype='int32')
        cell['Population'] = np.array([1], dtype='uint8')
        cell['Module'] = np.array([module], dtype='uint8')
        cell['Field Width'] = np.array(cell_field_width, dtype='float32')
        cell['Nx'] = np.array([self.xp.shape[0]], dtype='int32')
        cell['Ny'] = np.array([self.xp.shape[1]], dtype='int32')
        return cell

    def _build_grid_cell(self, gid, orientation, spacing, module):
        cell = {}
        cell['gid'] = np.array([gid], dtype='int32')
        cell['Population'] = np.array([0], dtype='uint8')
        cell['Module'] = np.array([module],dtype='uint8')
        cell['Grid Spacing'] = np.array([spacing],dtype='float32')
        cell['Grid Orientation'] = np.array([orientation],dtype='float32')
        cell['Nx'] = np.array([self.xp.shape[0]], dtype='int32')
        cell['Ny'] = np.array([self.xp.shape[1]], dtype='int32')
        if self.jitter_orientation:
            delta_orientation = self.local_random.uniform(init_orientation_jitter[0], init_orientation_jitter[1])
            cell['Jittered Grid Orientation'] = np.array([cell['Grid Orientation'][0] + delta_orientation], dtype='float32')
        if self.jitter_spacing: 
            delta_spacing = self.local_random.uniform(init_lambda_jitter[0], init_lambda_jitter[1])
            cell['Jittered Grid Spacing'] = np.array([cell['Grid Spacing'][0] + delta_spacing], dtype='float32')
        return cell

    def generate_xy_offsets(self):
        present = [False, False, False, False]
        if self.mpp_grid is not None:
            present[0] = True
        if self.mpp_place is not None:
            present[1] = True
        if self.lpp_grid is not None:
            present[2] = True
        if self.lpp_place is not None:
            present[3] = True

        _, xy_offsets, _, _ = generate_spatial_offsets(self.total_offsets, arena_dimension=arena_dimension, scale_factor=1.0)
        counter = 0
        if present[0]:
            counter = self._generate_xy_offsets(self.mpp_grid, xy_offsets, counter)
        if present[1]:
            counter = self._generate_xy_offsets(self.mpp_place, xy_offsets, counter)
        if present[2]:
            counter = self._generate_xy_offsets(self.lpp_grid, xy_offsets, counter)
        if present[3]:
            counter = self._generate_xy_offsets(self.lpp_place, xy_offsets, counter)
 
    def _generate_xy_offsets(self, cells, xy_offsets, counter):
        for key in cells.keys():
            nfields = 1
            cell = cells[key]
            if cell.has_key('Field Width'):
                nfields = cell['Num Fields'][0]
            cell['X Offset'] = np.asarray(xy_offsets[counter:counter+nfields,0], dtype='float32')
            cell['Y Offset'] = np.asarray(xy_offsets[counter:counter+nfields,1], dtype='float32')
            counter += nfields
        return counter

def calculate_module_centroids(cell_modules):
    module_x_centroids = [0.0 for _ in np.arange(nmodules)]
    module_y_centroids = [0.0 for _ in np.arange(nmodules)]
    for mod in cell_modules.keys():
        cells = cell_modules[mod] 
        curr_x, curr_y = [], []
        for cell in cells:
            xf, yf = cell['X Offset'], cell['Y Offset']
            for n in range(xf.shape[0]):
                curr_x.append(xf[n])
                curr_y.append(yf[n])
        curr_x, curr_y = np.asarray(xf, dtype='float32'), np.asarray(yf, dtype='float32')
        mean_x, mean_y = np.mean(curr_x), np.mean(curr_y)
        module_x_centroids[mod], module_y_centroids[mod] = mean_x, mean_y
    return module_x_centroids, module_y_centroids
    

def create_h5(comm, fn, template='dentate_h5types.h5'):
    if not os.path.isfile(fn):
        input_file  = h5py.File(template,'r')
        output_file = h5py.File(fn,'w')
        input_file.copy('/H5Types',output_file)
        input_file.close()
        output_file.close()
    comm.barrier()

def save_h5(comm, fn, data, population, namespace, template='dentate_h5types.h5'):
    create_h5(comm, fn)
    append_cell_attributes(fn, population, data, namespace=namespace, comm=comm, io_size=io_size, chunk_size=chunk_size, value_chunk_size=value_chunk_size)

def read_input_path(comm, feature_seed_offset, types_path, input_path, verbose): 
    rank = comm.Get_rank()
    mpp_grid, mpp_place = {}, {}
    tic = time.time()
    if input_path is not None:
        neuroh5_mpp_grid = read_cell_attributes('grid-'+input_path, 'MPP', namespace='Grid Input Features')
        for (gid, cell_attr) in neuroh5_mpp_grid:
            mpp_grid[gid] = cell_attr
        neuroh5_mpp_place = read_cell_attributes('place-'+input_path, 'MPP', namespace='Place Input Features')
        for (gid, cell_attr) in neuroh5_mpp_place:
            mpp_place[gid] = cell_attr
    else:
        cell_corpus = Cell_Population(comm, types_path, seed=feature_seed_offset)
        cell_corpus.full_init()
        mpp_grid = cell_corpus.mpp_grid
        mpp_place = cell_corpus.mpp_place
        

    if verbose:
        elapsed = time.time() - tic
        N = len(mpp_place.keys()) + len(mpp_grid.keys())
        print('%d cells initialized on rank %d in %f seconds' % (N,rank,elapsed))
    return mpp_grid, mpp_place

@click.command()
@click.option("--optimize", '-o', is_flag=True, required=True)
@click.option("--centroid", '-c', is_flag=True, required=False)
@click.option("--input-path", default=None, required=False, type=click.Path(file_okay=True, dir_okay=True))
@click.option("--types-path", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=True))
@click.option("--config", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--output-path", required=False, type=click.Path(file_okay=True, dir_okay=True))
@click.option("--verbose", "-v", is_flag=True, default=False)
@click.option("--lbound", type=float, required=False, default=1.)
@click.option("--ubound", type=float, required=False, default=50.)

def main(optimize, centroid, input_path, types_path, config, output_path, lbound, ubound, verbose):

    utils.config_logging(verbose)
    logger = utils.get_script_logger(script_name)
    tic = time.time()

    comm = MPI.COMM_WORLD
    rank = comm.rank
    env = Env(comm=comm, configFile=config)
    feature_seed_offset = int(env.modelConfig['Random Seeds']['Input Features'])

    mpp_grid, mpp_place = read_input_path(comm, feature_seed_offset, types_path, input_path, verbose)
    comm.barrier()

    logger.info('Saving temp...') 
    grid_temp_fn = os.path.join(os.path.dirname(output_path), ('grid-temp-%s' % (os.path.basename(output_path))))
    place_temp_fn = os.path.join(os.path.dirname(output_path), ('place-temp-%s' % (os.path.basename(output_path))))
    save_h5(comm, grid_temp_fn, mpp_grid, 'MPP', 'Grid Input Features', template=types_path)
    save_h5(comm, place_temp_fn, mpp_place, 'MPP', 'Place Input Features', template=types_path)

    cells = (mpp_grid, mpp_place)
    if optimize:
        main_optimization(comm, types_path, output_path, cells, lbound, ubound, centroid, verbose )
        elapsed = time.time() - tic
        if verbose:
            print('Took %f seconds' % elapsed)
    else:
        scale_factors = []
        f = open('optimal_sf.txt', 'r')
        for line in f.readlines():
            line = line.strip('\n')
            scale_factors.append(int(line))
        main_hardcoded(comm, output_path, cells, scale_factors)
        elapsed = time.time() - tic
        if verbose:
            print('Completed in %f seconds...' % elapsed)

def main_optimization(comm, types_path, output_path, cells, lbound, ubound, centroid, verbose):
    grid, place = cells
    init_parameters = None
    rank = comm.Get_rank()
    size = comm.Get_size()
    if (rank == 0):
        partition_border = np.linspace(lbound, ubound, nmodules+1)
        init_parameters = np.zeros((size, nmodules))
        for i in range(partition_border.shape[0]-1):
            mod_lb = partition_border[i]
            mod_ub = partition_border[i+1]
            init_parameters[:,i] = np.random.randint(mod_lb, mod_ub, size)
    init_parameters = comm.scatter(init_parameters, root=0)
    #init_scale_factors = np.random.randint(lbound, ubound+1, (iterations, nmodules))

    centroid_xbounds, centroid_ybounds = None, None
    cost_evals, params_list = [], []
    grid_copy = deepcopy(grid)
    place_copy = deepcopy(place)
    #scale_factor0 = init_parameters[t,:]
    scale_factor0 = init_parameters

    grid_module = gid_to_module_dictionary(grid)
    place_module = gid_to_module_dictionary(place)
    bounds = [(lbound, ubound) for sf in scale_factor0]
    if centroid:
        xp, yp = generate_mesh(scale_factor=1.0)
        xp_lb, xp_ub = np.min(xp), np.max(xp) + resolution
        yp_lb, yp_ub = np.min(yp), np.max(yp) + resolution
        centroid_xbounds = [(xp_lb, xp_ub) for sf in scale_factor0]
        centroid_ybounds = [(yp_lb, yp_ub) for sf in scale_factor0]
    if centroid_xbounds is not None and centroid_ybounds is not None:
        bounds += centroid_xbounds
        bounds += centroid_ybounds
    mesh = generate_mesh(scale_factor=1.0)
    param0 = None
    if centroid:
        cell_modules = module_merge(grid_module, place_module)
        module_x_centroids, module_y_centroids = calculate_module_centroids(cell_modules)
        x_centroid0 = [x for x in module_x_centroids]
        y_centroid0 = [y for y in module_y_centroids]
        param0 = np.concatenate((scale_factor0,x_centroid0,y_centroid0))
    else:
        param0 = scale_factor0
    if verbose:
        print(rank, param0)
    opt = OptimizationRoutine(comm, grid_module, place_module, mesh, lbound, ubound)
    best_x, params, costs = opt.optimize(param0, centroid=centroid, bounds=bounds, verbose=verbose)
    list_to_file(params, 'iteration-'+str(rank+1)+'-param.txt')        
    list_to_file(costs, 'iteration-'+str(rank+1)+'-costs.txt')        
    if centroid:
        cell_modules = module_merge(grid_module, place_module)
        prev_x_centroids, prev_y_centroids = calculate_module_centroids(cell_modules)
        curr_x_centroids, curr_y_centroids = best_x[nmodules:2*nmodules], best_x[2*nmodules:3*nmodules]
        x_translate = [curr_x_centroids[i] - prev_x_centroids[i] for i in range(len(prev_x_centroids))]
        y_translate = [curr_y_centroids[i] - prev_y_centroids[i] for i in range(len(prev_y_centroids))]
        translate_cells(grid_module, x_translate, y_translate, best_x[0:nmodules])
        #translate_cells(place_module, x_translate, y_translate, best_x[0:nmodules])
    cost_prepare_grid(best_x[0:nmodules], grid_module, mesh)
    cost_prepare_place(best_x[0:nmodules], place_module, mesh)
    grid_post_optimization = module_to_gid_dictionary(grid_module)
    place_post_optimization = module_to_gid_dictionary(place_module)

    grid_iteration_fn = os.path.join(os.path.dirname(output_path), ('grid-iteration-%i-%s' % (rank+1, os.path.basename(output_path))))
    place_iteration_fn = os.path.join(os.path.dirname(output_path), ('place-iteration-%i-%s' % (rank+1, os.path.basename(output_path))))
    save_h5(comm, grid_iteration_fn, grid_post_optimization, 'MPP', 'Grid Input Features', template=types_path)
    save_h5(comm, place_iteration_fn, place_post_optimization, 'MPP', 'Place Input Features', template=types_path)

def main_hardcoded(comm, output_path, cells, scale_factors):
    rank = comm.Get_rank()
    grid, place = cells
    grid_module = gid_to_module_dictionary(grid)
    place_module = gid_to_module_dictionary(place)
    #scale_cells_in_module(grid_module, scale_factors)
    #scale_cells_in_module(place_module, scale_factors)
    xp, yp = generate_mesh(scale_factor=1.0) 
    cost = cost_func(scale_factors, grid_module, place_module, (xp, yp), False, rank)
    grid_post_optimization = module_to_gid_dictionary(grid_module)
    place_post_optimization = module_to_gid_dictionary(place_module)

    grid_fn = os.path.join(os.path.dirname(output_path), ('grid-%s' % (os.path.basename(output_path))))
    place_fn = os.path.join(os.path.dirname(output_path), ('place-%s' % (os.path.basename(output_path))))
    
    save_h5(comm, grid_fn, grid_post_optimization, 'MPP', 'Grid Input Features')
    save_h5(comm, place_fn, place_post_optimization, 'MPP', 'Place Input Features')

def scale_cells_in_module(cell_modules, scale_factors):
    for module in cell_modules.keys():
        cells = cell_modules[module]
        scale_factor = scale_factors[module]
        for cell in cells:
            x_offset_scaled = cell['X Offset'] * scale_factor
            y_offset_scaled = cell['Y Offset'] * scale_factor
            cell['X Offset Scaled'] = np.asarray(x_offset_scaled, dtype='float32')
            cell['Y Offset Scaled'] = np.asarray(y_offset_scaled, dtype='float32')
        
def list_to_file(data, fn):
    data = np.asmatrix(data)
    f = open(fn, 'w')
    N, D = data.shape
    for n in range(N):
        for d in range(D):
            f.write(str(data[n,d]) + '\t')
        f.write('\n')
    f.close()

def gid_to_module_dictionary(cells):
    mod = {k:[] for k in np.arange(nmodules)}
    for key in cells.keys():
        cell = cells[key]
        curr_mod = cell['Module'][0]
        mod[curr_mod].append(cell)
    return mod

def module_to_gid_dictionary(module_cells):
    gid_dictionary = {}
    for mod in module_cells.keys():
        cells = module_cells[mod] 
        for cell in cells:
            gid = cell['gid'][0]
            gid_dictionary[gid] = cell
    return gid_dictionary
if __name__ == '__main__':
    main(args=sys.argv[(list_find(lambda s: s.find(script_name) != -1, sys.argv)+1):])
    
