"""
Dentate Gyrus network initialization routines.
"""
__author__ = 'See AUTHORS.md'

import itertools
import dentate
from dentate.neuron_utils import *
from dentate.utils import viewitems, zip_longest
from dentate import cells, synapses, lpt, lfp, simtime, io_utils
import h5py
from neuroh5.io import scatter_read_graph, bcast_graph, \
     scatter_read_trees, scatter_read_cell_attributes, \
     write_cell_attributes, read_cell_attribute_selection, \
     read_tree_selection, read_graph_selection
from neuron import h

# This logger will inherit its settings from the root logger, created in dentate.env
logger = get_module_logger(__name__)



# Code by Michael Hines from this discussion thread:
# https://www.neuron.yale.edu/phpBB/viewtopic.php?f=31&t=3628
def cx(env):
    """
    Estimates cell complexity. Uses the LoadBalance class.

    :param env: an instance of the `dentate.Env` class.
    """
    rank = int(env.pc.id())
    lb = h.LoadBalance()
    if os.path.isfile("mcomplex.dat"):
        lb.read_mcomplex()
    cxvec = h.Vector(len(env.gidset))
    for i, gid in enumerate(env.gidset):
        cxvec.x[i] = lb.cell_complexity(env.pc.gid2cell(gid))
    env.cxvec = cxvec
    return cxvec


def ld_bal(env):
    """
    For given cxvec on each rank, calculates the fractional load balance.

    :param env: an instance of the `dentate.Env` class.
    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())
    cxvec = env.cxvec
    sum_cx = sum(cxvec)
    max_sum_cx = env.pc.allreduce(sum_cx, 2)
    sum_cx = env.pc.allreduce(sum_cx, 1)
    if rank == 0:
        logger.info("*** expected load balance %.2f" % (sum_cx / nhosts / max_sum_cx))


def lpt_bal(env):
    """
    Load-balancing based on the LPT algorithm.
    Each rank has gidvec, cxvec: gather everything to rank 0, do lpt
    algorithm and write to a balance file.

    :param env: an instance of the `dentate.Env` class.
    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    cxvec = env.cxvec
    gidvec = list(env.gidset)
    # gather gidvec, cxvec to rank 0
    src = [None] * nhosts
    src[0] = list(zip(cxvec.to_python(), gidvec))
    dest = env.pc.py_alltoall(src)
    del src

    if rank == 0:
        lb = h.LoadBalance()
        allpairs = sum(dest, [])
        del dest
        parts = lpt.lpt(allpairs, nhosts)
        lpt.statistics(parts)
        part_rank = 0
        with open('parts.%d' % nhosts, 'w') as fp:
            for part in parts:
                for x in part[1]:
                    fp.write('%d %d\n' % (x[1], part_rank))
                part_rank = part_rank + 1


def register_cell(env, pop_name, gid, cell):
    """
    Registers a cell in a network environment.
    :param env: an instance of env.Env
    :param pop_name: population name
    :param gid: gid
    :param cell: cell instance
    """
    rank = env.comm.rank
    env.gidset.add(gid)
    env.cells.append(cell)
    env.pc.set_gid2node(gid, rank)
    # Tell the ParallelContext that this cell is a spike source
    # for all other hosts. NetCon is temporary.
    nc = cell.connect2target(h.nil)
    nc.delay = 0.1
    env.pc.cell(gid, nc, 1)
    # Record spikes of this cell
    env.pc.spike_record(gid, env.t_vec, env.id_vec)


def connect_cells(env, cleanup=True):
    """
    Loads NeuroH5 connectivity file, instantiates the corresponding
    synapse and network connection mechanisms for each postsynaptic cell.

    :param env:
    :param cleanup:

    """
    connectivityFilePath = env.connectivityFilePath
    forestFilePath = env.forestFilePath
    rank = int(env.pc.id())
    syn_attrs = env.synapse_attributes

    if rank == 0:
        logger.info('*** Connectivity file path is %s' % connectivityFilePath)
        logger.info('*** Reading projections: ')

    for (postsyn_name, presyn_names) in viewitems(env.projection_dict):

        synapse_config = env.celltypes[postsyn_name]['synapses']
        if 'correct_for_spines' in synapse_config:
            correct_for_spines = synapse_config['correct_for_spines']
        else:
            correct_for_spines = False

        if 'unique' in synapse_config:
            unique = synapse_config['unique']
        else:
            unique = False

        if 'weights' in synapse_config:
            has_weights = synapse_config['weights']
        else:
            has_weights = False

        if 'weights namespace' in synapse_config:
            weights_namespace = synapse_config['weights namespace']
        else:
            weights_namespace = 'Weights'

        if 'mech_file' in env.celltypes[postsyn_name]:
            mech_file_path = env.configPrefix + '/' + env.celltypes[postsyn_name]['mech_file']
        else:
            mech_file_path = None

        if rank == 0:
            logger.info('*** Reading synapse attributes of population %s' % (postsyn_name))

        if has_weights:
            cell_attr_namespaces = ['Synapse Attributes', weights_namespace]
        else:
            cell_attr_namespaces = ['Synapse Attributes']

        if env.nodeRanks is None:
            cell_attributes_dict = scatter_read_cell_attributes(forestFilePath, postsyn_name,
                                                                namespaces=cell_attr_namespaces, comm=env.comm,
                                                                io_size=env.IOsize)
        else:
            cell_attributes_dict = scatter_read_cell_attributes(forestFilePath, postsyn_name,
                                                                namespaces=cell_attr_namespaces, comm=env.comm,
                                                                node_rank_map=env.nodeRanks,
                                                                io_size=env.IOsize)
        cell_synapses_iter = cell_attributes_dict['Synapse Attributes']
        syn_attrs.init_syn_id_attrs_from_iter(cell_synapses_iter)
        
        if weights_namespace in cell_attributes_dict:
            syn_weights_iter = cell_attributes_dict[weights_namespace]
            first_gid = None
            for gid, cell_weights_dict in syn_weights_iter:
                if first_gid is None:
                    first_gid = gid
                weights_syn_ids = cell_weights_dict['syn_id']
                for syn_name in (syn_name for syn_name in cell_weights_dict if syn_name != 'syn_id'):
                    weights_values  = cell_weights_dict[syn_name]
                    syn_attrs.add_netcon_weights_from_iter(gid, syn_name, \
                                                           zip_longest(weights_syn_ids, \
                                                                       weights_values))
                    if rank == 0 and gid == first_gid:
                        logger.info('*** connect_cells: population: %s; gid: %i; found %i %s synaptic weights' %
                                    (postsyn_name, gid, len(cell_weights_dict[syn_name]), syn_name))
        del cell_attributes_dict

        first_gid = None
        for gid in syn_attrs.gids():
            if mech_file_path is not None:
                if first_gid is None:
                    first_gid = gid
                hoc_cell = env.pc.gid2cell(gid)
                biophys_cell = cells.BiophysCell(gid=gid, pop_name=postsyn_name, hoc_cell=hoc_cell, env=env)
                try:
                    cells.init_biophysics(biophys_cell, mech_file_path=mech_file_path, \
                                          reset_cable=True, from_file=True, correct_cm=correct_for_spines, \
                                          correct_g_pas=correct_for_spines, env=env)
                except IndexError:
                    raise IndexError('connect_cells: population: %s; gid: %i; could not load biophysics from path: '
                                     '%s' % (postsyn_name, gid, mech_file_path))
                env.biophys_cells[postsyn_name][gid] = biophys_cell
                if rank == 0 and gid == first_gid:
                    logger.info('*** connect_cells: population: %s; gid: %i; loaded biophysics from path: %s' %
                                (postsyn_name, gid, mech_file_path))

        for presyn_name in presyn_names:

            env.edge_count[postsyn_name][presyn_name] = 0

            if rank == 0:
                logger.info('*** Connecting %s -> %s' % (presyn_name, postsyn_name))

            logger.info('Rank %i: Reading projection %s -> %s' % (rank, presyn_name, postsyn_name))
            if env.nodeRanks is None:
                (graph, a) = scatter_read_graph(connectivityFilePath, comm=env.comm, io_size=env.IOsize,
                                                projections=[(presyn_name, postsyn_name)],
                                                namespaces=['Synapses', 'Connections'])
            else:
                (graph, a) = scatter_read_graph(connectivityFilePath, comm=env.comm, io_size=env.IOsize,
                                                node_rank_map=env.nodeRanks,
                                                projections=[(presyn_name, postsyn_name)],
                                                namespaces=['Synapses', 'Connections'])
            logger.info('Rank %i: Read projection %s -> %s' % (rank, presyn_name, postsyn_name))
            edge_iter = graph[postsyn_name][presyn_name]

            syn_params_dict = env.connection_config[postsyn_name][presyn_name].mechanisms

            last_time = time.time()
            syn_attrs.init_edge_attrs_from_iter(postsyn_name, presyn_name, a, edge_iter)
            logger.info('Rank %i: took %f s to initialize edge attributes for projection %s -> %s' % \
                        (rank, time.time() - last_time, presyn_name, postsyn_name))
            del graph[postsyn_name][presyn_name]

        pop_last_time = time.time()
        for gid in syn_attrs.gids():

            postsyn_cell = env.pc.gid2cell(gid)
            
            last_time = time.time()
            syn_count, mech_count, nc_count = synapses.config_hoc_cell_syns(env, gid, postsyn_name, \
                                                                            cell=postsyn_cell, unique=unique, \
                                                                            insert=True, \
                                                                            insert_netcons=True)
            if rank == 0:
                logger.info('Rank %i: took %f s to configure %i synapses, %i synaptic mechanisms, %i network connections for gid %d' % (rank, time.time() - last_time, syn_count, mech_count, nc_count, gid))

            env.edge_count[postsyn_name][presyn_name] += syn_count

            if cleanup:
                syn_attrs.del_syn_id_attr_dict(gid)
                if gid in env.biophys_cells[postsyn_name]:
                    del env.biophys_cells[postsyn_name][gid]

        if rank == 0:
            logger.info('Rank %i: took %f s to configure synapses for population %s' % (rank, time.time() - pop_last_time, postsyn_name))


def connect_cell_selection(env, cleanup=True):
    """
    Loads NeuroH5 connectivity file, instantiates the corresponding
    synapse and network connection mechanisms for the selected postsynaptic cells.

    TODO: cleanup might need to be more granular than binary
    :param env:
    :param cleanup:

    """
    connectivityFilePath = env.connectivityFilePath
    forestFilePath = env.forestFilePath
    rank = int(env.pc.id())
    syn_attrs = env.synapse_attributes

    if rank == 0:
        logger.info('*** Connectivity file path is %s' % connectivityFilePath)
        logger.info('*** Reading projections: ')

    pop_names = set([ s[0] for s in env.cell_selection ])
    gid_range = list(itertools.chain.from_iterable([ s[1] for s in env.cell_selection ]))
    
    vecstim_sources = defaultdict(list)
    
    for (postsyn_name, presyn_names) in viewitems(env.projection_dict):

        if postsyn_name not in pop_names:
            continue

        synapse_config = env.celltypes[postsyn_name]['synapses']
        if 'correct_for_spines' in synapse_config:
            correct_for_spines = synapse_config['correct_for_spines']
        else:
            correct_for_spines = False

        if 'unique' in synapse_config:
            unique = synapse_config['unique']
        else:
            unique = False

        if 'weights' in synapse_config:
            has_weights = synapse_config['weights']
        else:
            has_weights = False

        if 'weights namespace' in synapse_config:
            weights_namespace = synapse_config['weights namespace']
        else:
            weights_namespace = 'Weights'

        if 'mech_file' in env.celltypes[postsyn_name]:
            mech_file_path = env.configPrefix + '/' + env.celltypes[postsyn_name]['mech_file']
        else:
            mech_file_path = None

        if rank == 0:
                logger.info('*** Reading synapse attributes of population %s' % (postsyn_name))

        syn_attributes_iter = read_cell_attribute_selection(forestFilePath, postsyn_name,
                                                            namespace='Synapse Attributes', comm=env.comm,
                                                            io_size=env.IOsize)
        syn_attrs.init_syn_id_attrs_from_iter(syn_attributes_iter)
        del(syn_attributes_iter)
        
        if has_weights:
            weight_attributes_iter = read_cell_attribute_selection(forestFilePath, postsyn_name,
                                                                    namespace=weights_namespace, comm=env.comm,
                                                                    io_size=env.IOsize)
        else:
            weight_attributes_iter = None

        if weight_attributes_iter is not None:
            first_gid = None
            for gid, cell_weights_dict in weight_attributes_iter:
                if first_gid is None:
                    first_gid = gid
                weights_syn_ids = cell_weights_dict['syn_id']
                for syn_name in (syn_name for syn_name in cell_weights_dict if syn_name != 'syn_id'):
                    weights_values  = cell_weights_dict[syn_name]
                    syn_attrs.add_netcon_weights_from_iter(gid, syn_name, \
                                                           zip_longest(weights_syn_ids, \
                                                                       weights_values))
                    if rank == 0 and gid == first_gid:
                        logger.info('*** connect_cells: population: %s; gid: %i; found %i %s synaptic weights' %
                                    (postsyn_name, gid, len(cell_weights_dict[gid][syn_name]), syn_name))
            del weight_attributes_iter

        first_gid = None
        for gid in syn_attrs.gids():
            if mech_file_path is not None:
                if first_gid is None:
                    first_gid = gid
                biophys_cell = cells.BiophysCell(gid=gid, pop_name=postsyn_name, hoc_cell=env.pc.gid2cell(gid), env=env)
                try:
                    cells.init_biophysics(biophys_cell, \
                                          mech_file_path=mech_file_path, \
                                          reset_cable=True, \
                                          from_file=True, \
                                          correct_cm=correct_for_spines, \
                                          correct_g_pas=correct_for_spines, \
                                          env=env)
                except IndexError:
                    raise IndexError('connect_cells: population: %s; gid: %i; could not load biophysics from path: '
                                     '%s' % (postsyn_name, gid, mech_file_path))
                env.biophys_cells[postsyn_name][gid] = biophys_cell
                if rank == 0 and gid == first_gid:
                    logger.info('*** connect_cells: population: %s; gid: %i; loaded biophysics from path: %s' %
                                (postsyn_name, gid, mech_file_path))

        for presyn_name in presyn_names:

            env.edge_count[postsyn_name][presyn_name] = 0

            if rank == 0:
                logger.info('*** Connecting %s -> %s' % (presyn_name, postsyn_name))

            (graph, a) = read_graph_selection(connectivityFilePath, gid_range,
                                              comm=env.comm, io_size=env.IOsize,
                                              projections=[(presyn_name, postsyn_name)],
                                              namespaces=['Synapses', 'Connections'])
                
            
            syn_params_dict = env.connection_config[postsyn_name][presyn_name].mechanisms

            edge_iters = itertools.tee(graph[postsyn_name][presyn_name])

            syn_attrs.init_edge_attrs_from_iter(postsyn_name, presyn_name, a, \
                                                itertools.imap(lambda edge: vecstim_sources.append(edge[0]), \
                                                               edge_iters))
            del graph[postsyn_name][presyn_name]

        for gid in syn_attrs.gids():

            postsyn_cell = env.pc.gid2cell(gid)
            syn_count, mech_count, nc_count = synapses.config_hoc_cell_syns(env, gid, postsyn_name, \
                                                                            cell=postsyn_cell, unique=unique, \
                                                                            insert=True, insert_netcons=True)
            env.edge_count[postsyn_name][presyn_name] += syn_count
            if cleanup:
                syn_attrs.del_syn_id_attr_dict(gid)
                if gid in env.biophys_cells[postsyn_name]:
                    del env.biophys_cells[postsyn_name][gid]

    return vecstim_sources

def connect_gjs(env):
    """
    Loads NeuroH5 connectivity file, instantiates the corresponding half-gap mechanisms on the pre- and post-junction
    cells.
    :param env: :class:'Env'
    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    datasetPath = os.path.join(env.dataset_prefix, env.datasetName)

    gapjunctions = env.gapjunctions
    gapjunctionsFilePath = env.gapjunctionsFilePath 

    num_gj = 0
    num_gj_intra = 0
    num_gj_inter = 0
    if gapjunctionsFilePath is not None:

        (graph, a) = bcast_graph(gapjunctionsFilePath,\
                                 namespaces=['Coupling strength','Location'],\
                                 comm=env.comm)

        ggid = 2e6
        for name in list(gapjunctions.keys()):
            if rank == 0:
                logger.info("*** Creating gap junctions %s" % str(name))
            prj = graph[name[0]][name[1]]
            attrmap = a[(name[1],name[0])]
            cc_src_idx = attrmap['Coupling strength']['Source']
            cc_dst_idx = attrmap['Coupling strength']['Destination']
            dstsec_idx = attrmap['Location']['Destination section']
            dstpos_idx = attrmap['Location']['Destination position']
            srcsec_idx = attrmap['Location']['Source section']
            srcpos_idx = attrmap['Location']['Source position']

            for src in sorted(prj.keys()):
                edges        = prj[src]
                destinations = edges[0]
                cc_dict      = edges[1]['Coupling strength']
                loc_dict     = edges[1]['Location']
                srcweights   = cc_dict[cc_src_idx]
                dstweights   = cc_dict[cc_dst_idx]
                dstposs      = loc_dict[dstpos_idx]
                dstsecs      = loc_dict[dstsec_idx]
                srcposs      = loc_dict[srcpos_idx]
                srcsecs      = loc_dict[srcsec_idx]
                for i in range(0,len(destinations)):
                    dst       = destinations[i]
                    srcpos    = srcposs[i]
                    srcsec    = srcsecs[i]
                    dstpos    = dstposs[i]
                    dstsec    = dstsecs[i]
                    wgt       = srcweights[i]*0.001
                    if env.pc.gid_exists(src):
                        if rank == 0:
                            logger.info('host %d: gap junction: gid = %d sec = %d coupling = %g '
                                        'sgid = %d dgid = %d\n' %
                                        (rank, src, srcsec, wgt, ggid, ggid+1))
                        cell = env.pc.gid2cell(src)
                        gj = mkgap(env, cell, src, srcpos, srcsec, ggid, ggid+1, wgt)
                    if env.pc.gid_exists(dst):
                        if rank == 0:
                            logger.info('host %d: gap junction: gid = %d sec = %d coupling = %g '
                                        'sgid = %d dgid = %d\n' %
                                        (rank, dst, dstsec, wgt, ggid+1, ggid))
                        cell = env.pc.gid2cell(dst)
                        gj = mkgap(env, cell, dst, dstpos, dstsec, ggid+1, ggid, wgt)
                    ggid = ggid+2
                    if env.pc.gid_exists(src) or env.pc.gid_exists(dst):
                        num_gj += 1
                        if env.pc.gid_exists(src) and env.pc.gid_exists(dst):
                            num_gj_intra += 1
                        else:
                            num_gj_inter += 1
                        

            del graph[name[0]][name[1]]
        
        logger.info('*** host %d: created total %i gap junctions: %i intraprocessor %i interprocessor' % (rank, num_gj, num_gj_intra, num_gj_inter))


def make_cells(env):
    """
    Instantiates cell templates according to population ranges and NeuroH5 morphology if present.

    :param env:
    :return:
    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    v_sample_seed = int(env.modelConfig['Random Seeds']['Intracellular Voltage Sample'])
    ranstream_v_sample = np.random.RandomState()
    ranstream_v_sample.seed(v_sample_seed)

    datasetPath = env.datasetPath
    dataFilePath = env.dataFilePath
    pop_names = sorted(env.celltypes.keys())

    for pop_name in pop_names:
        if rank == 0:
            logger.info("*** Creating population %s" % pop_name)
        env.load_cell_template(pop_name)

        v_sample_set = set([])
        env.v_sample_dict[pop_name] = v_sample_set
        
        for gid in range(env.celltypes[pop_name]['start'],
                         env.celltypes[pop_name]['start'] + env.celltypes[pop_name]['num']):
            if ranstream_v_sample.uniform() <= env.vrecordFraction:
                v_sample_set.add(gid)

        num_cells = 0
        if (pop_name in env.cellAttributeInfo) and ('Trees' in env.cellAttributeInfo[pop_name]):
            if rank == 0:
                logger.info("*** Reading trees for population %s" % pop_name)

            if env.nodeRanks is None:
                (trees, forestSize) = scatter_read_trees(dataFilePath, pop_name, comm=env.comm, io_size=env.IOsize)
            else:
                (trees, forestSize) = scatter_read_trees(dataFilePath, pop_name, comm=env.comm, io_size=env.IOsize,
                                                         node_rank_map=env.nodeRanks)
            if rank == 0:
                logger.info("*** Done reading trees for population %s" % pop_name)

            for i, (gid, tree) in enumerate(trees):
                if rank == 0:
                    logger.info("*** Creating %s gid %i" % (pop_name, gid))

                model_cell = cells.make_hoc_cell(env, pop_name, gid, neurotree_dict=tree)
                if rank == 0 and i == 0:
                    for sec in list(model_cell.all):
                        h.psection(sec=sec)
                register_cell(env, pop_name, gid, model_cell)
                # Record voltages from a subset of cells
                if model_cell.is_art() == 0:
                    if gid in env.v_sample_dict[pop_name]: 
                        env.recs_dict[pop_name][gid] = make_rec(gid, pop_name, gid, model_cell, sec=list(model_cell.soma)[0], \
                                                                dt=env.dt, loc=0.5, param='v', description='Soma V')



                num_cells += 1

        elif (pop_name in env.cellAttributeInfo) and ('Coordinates' in env.cellAttributeInfo[pop_name]):
            if rank == 0:
                logger.info("*** Reading coordinates for population %s" % pop_name)

            if env.nodeRanks is None:
                cell_attributes_dict = scatter_read_cell_attributes(dataFilePath, pop_name,
                                                                    namespaces=['Coordinates'],
                                                                    comm=env.comm, io_size=env.IOsize)
            else:
                cell_attributes_dict = scatter_read_cell_attributes(dataFilePath, pop_name,
                                                                    namespaces=['Coordinates'],
                                                                    node_rank_map=env.nodeRanks,
                                                                    comm=env.comm, io_size=env.IOsize)
            if rank == 0:
                logger.info("*** Done reading coordinates for population %s" % pop_name)

            coords = cell_attributes_dict['Coordinates']

            for i, (gid, cell_coords_dict) in enumerate(coords):
                if rank == 0:
                    logger.info("*** Creating %s gid %i" % (pop_name, gid))

                model_cell = cells.make_hoc_cell(env, pop_name, gid)

                cell_x = cell_coords_dict['X Coordinate'][0]
                cell_y = cell_coords_dict['Y Coordinate'][0]
                cell_z = cell_coords_dict['Z Coordinate'][0]
                model_cell.position(cell_x, cell_y, cell_z)

                register_cell(env, pop_name, gid, model_cell)
                num_cells += 1

        h.define_shape()
        if rank == 0:
            logger.info("*** Created %i cells" % num_cells)

        
def make_cell_selection(env):
    """
    Instantiates cell templates for the selected cells according to population ranges and NeuroH5 morphology if present.

    :param env:
    :param cell_selection:
    :return:
    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    datasetPath = env.datasetPath
    dataFilePath = env.dataFilePath
    
    pop_names = set([ s[0] for s in env.cell_selection ])

    for pop_name in pop_names:
        if rank == 0:
            logger.info("*** Creating selected cells from population %s" % pop_name)
        env.load_cell_template(pop_name)
        templateClass = getattr(h, env.celltypes[pop_name]['template'])

        v_sample_set = set([])

        gid_range = [ s[1] + env.celltypes[pop_name]['start'] for s in env.cell_selection if s[0] == pop_name ]
        for gid in gid_range:
            v_sample_set.add(gid)

        if (pop_name in env.cellAttributeInfo) and ('Trees' in env.cellAttributeInfo[pop_name]):
            if rank == 0:
                logger.info("*** Reading trees for population %s" % pop_name)

            (trees, _) = read_tree_selection(dataFilePath, pop_name, gid_range, comm=env.comm, io_size=env.IOsize)
            if rank == 0:
                logger.info("*** Done reading trees for population %s" % pop_name)

            i = 0
            for (gid, tree) in trees:
                if rank == 0:
                    logger.info("*** Creating %s gid %i" % (pop_name, gid))

                model_cell = cells.make_neurotree_cell(templateClass, neurotree_dict=tree, gid=gid, 
                                                       dataset_path=datasetPath)
                if rank == 0 and i == 0:
                    for sec in list(model_cell.all):
                        h.psection(sec=sec)
                env.gidset.add(gid)
                env.cells.append(model_cell)
                env.pc.set_gid2node(gid, rank)
                # Tell the ParallelContext that this cell is a spike source
                # for all other hosts. NetCon is temporary.
                nc = model_cell.connect2target(h.nil)
                env.pc.cell(gid, nc, 1)
                # Record spikes of this cell
                env.pc.spike_record(gid, env.t_vec, env.id_vec)
                if model_cell.is_art() == 0:
                    if gid in env.v_sample_dict[pop_name]: 
                        env.recs_dict[pop_name][gid] = make_rec(gid, pop_name, gid, model_cell, sec=list(model_cell.soma)[0], \
                                                                dt=env.dt, loc=0.5, param='v', description='Soma V')

                i = i + 1
            if rank == 0:
                logger.info("*** Created %i cells" % i)

        elif (pop_name in env.cellAttributeInfo) and ('Coordinates' in env.cellAttributeInfo[pop_name]):
            if rank == 0:
                logger.info("*** Reading coordinates for population %s" % pop_name)

            cell_attributes_dict = read_cell_attribute_selection(dataFilePath, pop_name, namespace='Coordinates', comm=env.comm)

            if rank == 0:
                logger.info("*** Done reading coordinates for population %s" % pop_name)

            i = 0
            cell_attributes_iter = cell_attributes_dict['Coordinates']
            for (gid, cell_coords_dict) in cell_attributes_iter:
                if rank == 0:
                    logger.info("*** Creating %s gid %i" % (pop_name, gid))

                model_cell = cells.make_hoc_cell(env, pop_name, gid)

                cell_x = cell_coords_dict['X Coordinate'][0]
                cell_y = cell_coords_dict['Y Coordinate'][0]
                cell_z = cell_coords_dict['Z Coordinate'][0]
                model_cell.position(cell_x, cell_y, cell_z)

                env.gidset.add(gid)
                env.cells.append(model_cell)
                env.pc.set_gid2node(gid, rank)
                # Tell the ParallelContext that this cell is a spike source
                # for all other hosts. NetCon is temporary.
                nc = model_cell.connect2target(h.nil)
                env.pc.cell(gid, nc, 1)
                # Record spikes of this cell
                env.pc.spike_record(gid, env.t_vec, env.id_vec)
                if model_cell.is_art() == 0:
                    if gid in env.v_sample_dict[pop_name]: 
                        env.recs_dict[pop_name][gid] = make_rec(gid, pop_name, gid, model_cell, sec=list(model_cell.soma)[0], \
                                                                dt=env.dt, loc=0.5, param='v', description='Soma V')

                i = i + 1
        h.define_shape()


def make_stimulus(env,vecstim_sources):
    """
    Loads spike train data from NeuroH5 file for those populations
    that have 'Vector Stimulus' entry in the cell configuration.

    :param env:
    :return:

    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    datasetPath = env.datasetPath
    inputFilePath = env.dataFilePath

    pop_names = list(env.celltypes.keys())
    pop_names.sort()
    for pop_name in pop_names:
        if 'Vector Stimulus' in env.celltypes[pop_name]:
            vecstim_namespace = env.celltypes[pop_name]['Vector Stimulus']

            if env.nodeRanks is None:
                cell_attributes_dict = scatter_read_cell_attributes(inputFilePath, pop_name,
                                                                    namespaces=[vecstim_namespace],
                                                                    comm=env.comm, io_size=env.IOsize)
            else:
                cell_attributes_dict = scatter_read_cell_attributes(inputFilePath, pop_name,
                                                                    namespaces=[vecstim_namespace],
                                                                    node_rank_map=env.nodeRanks,
                                                                    comm=env.comm, io_size=env.IOsize)
            cell_vecstim = cell_attributes_dict[vecstim_namespace]
            if rank == 0:
                logger.info("*** Stimulus onset is %g ms" % env.stimulus_onset)
            for (gid, vecstim_dict) in cell_vecstim:
                if len(vecstim_dict['spiketrain']) > 0:
                    logger.info("*** Spike train for gid %i is of length %i (first spike at %g ms)" %
                                (gid, len(vecstim_dict['spiketrain']), vecstim_dict['spiketrain'][0]))
                else:
                    logger.info("*** Spike train for gid %i is of length %i" %
                                (gid, len(vecstim_dict['spiketrain'])))

                vecstim_dict['spiketrain'] += env.stimulus_onset
                cell = env.pc.gid2cell(gid)
                cell.play(h.Vector(vecstim_dict['spiketrain']))

    if vecstim_sources is not None:
        gid_range_inst = list(itertools.chain.from_iterable([ s[1] for s in env.cell_selection ]))
        if env.spike_input_path is None:
            raise RuntimeException("Spike input path not provided")
        if env.spike_input_ns is None:
            raise RuntimeException("Spike input namespace not provided")
        for pop_name, gid_range_stim in viewitems(vecstim_sources):
            gid_range1 = gid_range_stim.difference(gid_range_inst)
            cell_spikes = read_cell_attribute_selection(env.spike_input_path, list(gid_range1), \
                                                        namespace=env.spike_input_ns, \
                                                        comm=env.comm, io_size=env.IOsize)
            for gid in gid_range1:
                stim_cell = h.VecStim()
                stim_cell.play(cell_spikes[gid])
                register_cell(env, pop_name, gid, stim_cell)

def init(env,profile=False):
    """Initializes the network by calling make_cells, make_stimulus, connect_cells, connect_gjs.

    Optionally performs load balancing.

    :param env:
    """
    from neuron import h
    configure_hoc_env(env)

    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())
    if env.optldbal or env.optlptbal:
        lb = h.LoadBalance()
        if not os.path.isfile("mcomplex.dat"):
            lb.ExperimentalMechComplex()

    if rank == 0:
        io_utils.mkout(env, env.resultsFilePath)
    if rank == 0:
        logger.info("*** Creating cells...")
    h.startsw()
    env.pc.barrier()
    if env.cell_selection is None:
        make_cells(env)
    else:
        make_cell_selection(env)
    if profile and rank == 0:
        from guppy import hpy
        h = hpy()
        logger.info(h.heap())
    env.pc.barrier()
    env.mkcellstime = h.stopsw()
    if rank == 0:
        logger.info("*** Cells created in %g seconds" % env.mkcellstime)
    logger.info("*** Rank %i created %i cells" % (rank, len(env.cells)))
    if env.cell_selection is None:
        h.startsw()
        connect_gjs(env)
        env.pc.setup_transfer()
        env.pc.set_maxstep(10.0)
        env.pc.barrier()
        env.connectgjstime = h.stopsw()
        if rank == 0:
            logger.info("*** Gap junctions created in %g seconds" % env.connectgjstime)
    if profile and rank == 0:
        from guppy import hpy
        h = hpy()
        logger.info(h.heap())
    h.startsw()
    if env.cell_selection is None:
        connect_cells(env)
        vecstim_selection = None
    else:
        vecstim_selection = connect_cell_selection(env)
    env.pc.barrier()
    env.connectcellstime = h.stopsw()
    if profile and rank == 0:
        from guppy import hpy
        h = hpy()
        logger.info(h.heap())
    if rank == 0:
        logger.info("*** Connections created in %g seconds" % env.connectcellstime)
    edge_count = int(sum([env.edge_count[dest][source] for dest in env.edge_count for source in env.edge_count[dest]]))
    logger.info("*** Rank %i created %i connections" % (rank, edge_count))
    h.startsw()
    make_stimulus(env,vecstim_selection)
    env.mkstimtime = h.stopsw()
    if rank == 0:
        logger.info("*** Stimuli created in %g seconds" % env.mkstimtime)
    h.startsw()
    if env.cell_selection is None:
        for lfp_label,lfp_config_dict in viewitems(env.lfpConfig):
            env.lfp[lfp_label] = \
              lfp.LFP(lfp_label, env.pc, env.celltypes, lfp_config_dict['position'], rho=lfp_config_dict['rho'],
                        dt_lfp=lfp_config_dict['dt'], fdst=lfp_config_dict['fraction'],
                        maxEDist=lfp_config_dict['maxEDist'],
                        seed=int(env.modelConfig['Random Seeds']['Local Field Potential']))
        if rank == 0:
            logger.info("*** LFP objects instantiated")
    lfp_time = h.stopsw()
    setup_time           = env.mkcellstime + env.mkstimtime + env.connectcellstime + env.connectgjstime + lfp_time
    max_setup_time       = env.pc.allreduce(setup_time, 2) ## maximum value
    env.simtime          = simtime.SimTimeEvent(env.pc, env.max_walltime_hrs, env.results_write_time, max_setup_time)
    h.v_init = env.v_init
    h.stdinit()
    h.finitialize(env.v_init)
    if env.optldbal or env.optlptbal:
        cx(env)
        ld_bal(env)
        if env.optlptbal:
            lpt_bal(env)


def run(env, output=True):
    """
    Runs network simulation. Assumes that procedure `init` has been
    called with the network configuration provided by the `env`
    argument.

    :param env:
    :param output: bool

    """
    rank = int(env.pc.id())
    nhosts = int(env.pc.nhost())

    if rank == 0:
        logger.info("*** Running simulation")

    env.pc.barrier()
    env.pc.psolve(h.tstop)

    if rank == 0:
        logger.info("*** Simulation completed")
    del env.cells
    env.pc.barrier()
    if output:
        if rank == 0:
            logger.info("*** Writing spike data")
        io_utils.spikeout(env, env.resultsFilePath)
        if env.vrecordFraction > 0.:
          if rank == 0:
            logger.info("*** Writing intracellular trace data")
          t_vec = np.arange(0, h.tstop+h.dt, h.dt, dtype=np.float32)
          io_utils.recsout(env, env.resultsFilePath)
        env.pc.barrier()
        if rank == 0:
            logger.info("*** Writing local field potential data")
            io_utils.lfpout(env, env.resultsFilePath)

    comptime = env.pc.step_time()
    cwtime   = comptime + env.pc.step_wait()
    maxcw    = env.pc.allreduce(cwtime, 2)
    meancomp = env.pc.allreduce(comptime, 1)/nhosts
    maxcomp  = env.pc.allreduce(comptime, 2)

    gjtime   = env.pc.vtransfer_time()

    gjvect   = h.Vector()
    env.pc.allgather(gjtime, gjvect)
    meangj = gjvect.mean()
    maxgj  = gjvect.max()
    
    if rank == 0:
        logger.info("Execution time summary for host %i:" % rank)
        logger.info("  created cells in %g seconds" % env.mkcellstime)
        logger.info("  connected cells in %g seconds" % env.connectcellstime)
        logger.info("  created gap junctions in %g seconds" % env.connectgjstime)
        logger.info("  ran simulation in %g seconds" % comptime)
        logger.info("  spike communication time: %g seconds" % env.pc.send_time())
        logger.info("  event handling time: %g seconds" % env.pc.event_time())
        logger.info("  numerical integration time: %g seconds" % env.pc.integ_time())
        logger.info("  voltage transfer time: %g seconds" % gjtime)
        if maxcw > 0:
            logger.info("Load balance = %g" % (meancomp/maxcw))
        if meangj > 0:
            logger.info("Mean/max voltage transfer time: %g / %g seconds" % (meangj, maxgj))
            for i in range(nhosts):
                logger.info("Voltage transfer time on host %i: %g seconds" % (i, gjvect.x[i]))

    env.pc.runworker()
    env.pc.done()
    h.quit()
