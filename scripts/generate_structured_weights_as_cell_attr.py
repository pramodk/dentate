import sys, os, time, gc, click, logging
from collections import defaultdict
import numpy as np
from mpi4py import MPI
import neuroh5
from neuroh5.io import append_cell_attributes, read_population_ranges, bcast_cell_attributes, \
    scatter_read_cell_attributes, read_cell_attribute_selection, NeuroH5ProjectionGen
import dentate
from dentate.env import Env
from dentate import utils, stimulus, synapses
from dentate.utils import *
import h5py

context = Context()


def mpi_excepthook(type, value, traceback):
    sys_excepthook(type, value, traceback)
    if MPI.COMM_WORLD.size > 1:
        MPI.COMM_WORLD.Abort(1)
sys_excepthook = sys.excepthook
sys.excepthook = mpi_excepthook


    

@click.command()
@click.option("--config", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--input-features-path", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--input-features-namespaces", type=str, multiple=True, default=['Place Selectivity', 'Grid Selectivity'])
@click.option("--output-weights-path", required=True, type=click.Path(exists=False, file_okay=True, dir_okay=False))
@click.option("--initial-weights-path", required=False, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--h5types-path", required=False, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--synapse-name", type=str, default='AMPA')
@click.option("--initial-weights-namespace", type=str, default='Weights')
@click.option("--output-weights-namespace", type=str, default='Structured Weights')
@click.option("--connections-path", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False))
@click.option("--destination", '-d', type=str)
@click.option("--sources", '-s', type=str, multiple=True)
@click.option("--arena-id", '-a', type=str, default='A')
@click.option("--field-width-scale", type=float, default=1.2)
@click.option("--max-delta-weight", type=float, default=4.)
@click.option("--optimize-method", type=str, default='L-BFGS-B')
@click.option("--max-iter", type=int, default=10)
@click.option("--io-size", type=int, default=-1)
@click.option("--chunk-size", type=int, default=1000)
@click.option("--value-chunk-size", type=int, default=1000)
@click.option("--cache-size", type=int, default=50)
@click.option("--write-size", type=int, default=1)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--plot", is_flag=True)
def main(config, input_features_path, input_features_namespaces, output_weights_path, initial_weights_path, h5types_path, synapse_name, initial_weights_namespace, output_weights_namespace, connections_path, destination, sources, arena_id, field_width_scale, max_delta_weight, optimize_method, max_iter,  io_size, chunk_size, value_chunk_size, cache_size, write_size, verbose, dry_run, plot):
    """

    :param config: str (path to .yaml file)
    :param input_features_path: str (path to .h5 file)
    :param initial_weights_path: str (path to .h5 file)
    :param initial_weights_namespace: str
    :param output_weights_namespace: str
    :param connections_path: str (path to .h5 file)
    :param destination: str
    :param sources: list of str
    :param io_size:
    :param chunk_size:
    :param value_chunk_size:
    :param cache_size:
    :param write_size:
    :param verbose:
    :param dry_run:
    :return:
    """

    utils.config_logging(verbose)
    logger = utils.get_script_logger(__file__)

    comm = MPI.COMM_WORLD
    rank = comm.rank
    nranks = comm.size

    if io_size == -1:
        io_size = comm.size
    if rank == 0:
        logger.info('%s: %i ranks have been allocated' % (__file__, comm.size))

    env = Env(comm=comm, config_file=config, io_size=io_size)

    if (not dry_run) and (rank==0):
        if not os.path.isfile(output_weights_path):
            if initial_weights_path is not None:
                input_file  = h5py.File(initial_weights_path,'r')
            elif h5types_path is not None:
                input_file  = h5py.File(h5types_path,'r')
            else:
                raise RuntimeError('h5types input path must be specified when weights path is not specified.')
            output_file = h5py.File(output_weights_path,'w')
            input_file.copy('/H5Types',output_file)
            input_file.close()
            output_file.close()
    env.comm.barrier()

    this_output_weights_namespace = '%s %s' % (output_weights_namespace, arena_id)
    this_input_features_namespaces = ['%s %s' % (input_features_namespace, arena_id) for input_features_namespace in input_features_namespaces]

    initial_weights_dict = None

    selectivity_type_index = { i: n for n, i in viewitems(env.selectivity_types) }
    target_selectivity_type_name = 'place'
    target_selectivity_type = env.selectivity_types[target_selectivity_type_name]
    features_attrs = defaultdict(dict)
    source_features_attr_names = ['Selectivity Type', 'Num Fields', 'Field Width', 'Peak Rate',
                                  'X Offset', 'Y Offset', 'Arena Rate Map']
    target_features_attr_names = ['Selectivity Type', 'Num Fields', 'Field Width', 'Peak Rate',
                                  'X Offset', 'Y Offset']

    local_random = np.random.RandomState()

    seed_offset = int(env.model_config['Random Seeds']['GC Structured Weights'])
    spatial_resolution = env.stimulus_config['Spatial Resolution'] # cm

    arena = env.stimulus_config['Arena'][arena_id]
    default_run_vel = arena.properties['default run velocity']  # cm/s

    arena_x, arena_y = stimulus.get_2D_arena_spatial_mesh(arena, spatial_resolution)
    
    gid_count = 0
    start_time = time.time()

    connection_gen_list = [ NeuroH5ProjectionGen(connections_path, source, destination, namespaces=['Synapses'], comm=comm) \
                               for source in sources ]

    structured_weights_dict = {}
    for iter_count, attr_gen_package in enumerate(zip_longest(*connection_gen_list)):
        
        local_time = time.time()
        this_gid = attr_gen_package[0][0]
        if not all([attr_gen_items[0] == this_gid for attr_gen_items in attr_gen_package]):
            raise Exception('Rank: %i; destination: %s; this_gid not matched across multiple attribute '
                            'generators: %s' % (rank, destination,
                                                [attr_gen_items[0] for attr_gen_items in attr_gen_package]))


        if this_gid is None:
            selection = []
            logger.info('Rank: %i received None' % rank)
        else:
            selection = [this_gid]
            local_random.seed(int(this_gid + seed_offset))

        initial_weights_by_syn_id_dict = {}
        initial_weights_by_source_gid_dict = {}

        if initial_weights_path is not None:
            initial_weights_iter = \
              read_cell_attribute_selection(initial_weights_path, destination,
                                            namespace=initial_weights_namespace,
                                            selection=selection)
            syn_weight_attr_dict = dict(initial_weights_iter)

            syn_ids = syn_weight_attr_dict[target_gid]['syn_id']
            weights = syn_weight_attr_dict[target_gid][synapse_name]

            for (syn_id, weight) in zip(syn_ids, weights):
                initial_weights_by_syn_id_dict[int(syn_id)] = float(weight)

            logger.info('destination: %s; gid %i; read initial synaptic weights for %i synapses' %
                        (destination, this_gid, len(initial_weights_by_syn_id_dict)))

        syn_count_by_source_gid_dict = defaultdict(int)
        source_gid_set_dict = defaultdict(set)
        syn_ids_by_source_gid_dict = defaultdict(list)
        structured_syn_id_count = 0
        for source, (destination_gid, (source_gid_array, conn_attr_dict)) in zip_longest(sources, attr_gen_package):
            syn_ids = conn_attr_dict['Synapses']['syn_id']
            count = 0
            for i in range(len(source_gid_array)):
                this_source_gid = source_gid_array[i]
                this_syn_id = syn_ids[i]
                this_syn_wgt = initial_weights_by_syn_id_dict.get(this_syn_id, 1.0)
                source_gid_set_dict[source].add(this_source_gid)
                syn_ids_by_source_gid_dict[this_source_gid].append(this_syn_id)
                syn_count_by_source_gid_dict[this_source_gid] += 1
                if this_source_gid not in initial_weights_by_source_gid_dict:
                    initial_weights_by_source_gid_dict[this_source_gid] = this_syn_wgt

                count += 1
            structured_syn_id_count += len(syn_ids)
            logger.info('Rank %i; destination: %s; gid %i; %d edges from source population %s' %
                        (rank, destination, this_gid, count, source))
                    
        target_rate_maps = {}
        for input_features_namespace in this_input_features_namespaces:
            input_features_iter = read_cell_attribute_selection(input_features_path, destination, 
                                                                namespace=input_features_namespace,
                                                                mask=set(target_features_attr_names), 
                                                                comm=env.comm, selection=selection)
            count = 0
            for gid, attr_dict in input_features_iter:
                input_cell_config = stimulus.get_input_cell_config(target_selectivity_type,
                                                                   selectivity_type_index,
                                                                   selectivity_attr_dict=attr_dict)
                if input_cell_config.num_fields > 0:
                    input_cell_config.field_width *= field_width_scale
                    target_map = np.asarray(input_cell_config.get_rate_map(arena_x, arena_y),
                                            dtype=np.float32)
                    target_rate_maps[gid] = target_map
                    count += 1
            if rank == 0:
                logger.info('Read %s feature data for %i cells in population %s' % (input_features_namespace, count, destination))

        input_rate_maps_by_source_gid_dict = {}
        for source in sources:
            source_gids = list(source_gid_set_dict[source])
            if rank == 0:
                logger.info('Reading %s feature data for %i cells in population %s...' % (input_features_namespace, len(source_gids), source))
            for input_features_namespace in this_input_features_namespaces:
                input_features_iter = read_cell_attribute_selection(input_features_path, source, 
                                                                    namespace=input_features_namespace,
                                                                    mask=set(source_features_attr_names), 
                                                                    comm=env.comm, selection=source_gids)
                count = 0
                for gid, attr_dict in input_features_iter:
                    input_rate_maps_by_source_gid_dict[gid] = attr_dict['Arena Rate Map']
                    count += 1
                if rank == 0:
                    logger.info('Read %s feature data for %i cells in population %s' % (input_features_namespace, count, source))

        output_weights_dict = {}
        if this_gid is not None and len(target_rate_maps) > 0:

            if is_interactive:
                context.update(locals())

            normalized_delta_weights_dict, arena_LS_map = \
              synapses.generate_structured_weights(target_map=target_rate_maps[this_gid],
                                                initial_weight_dict=initial_weights_by_source_gid_dict,
                                                input_rate_map_dict=input_rate_maps_by_source_gid_dict,
                                                syn_count_dict=syn_count_by_source_gid_dict,
                                                max_delta_weight=max_delta_weight, arena_x=arena_x, arena_y=arena_y,
                                                optimize_method=optimize_method, verbose=verbose,
                                                plot=plot)

            output_syn_ids = np.empty(structured_syn_id_count, dtype='uint32')
            output_weights = np.empty(structured_syn_id_count, dtype='float32')
            i = 0
            for source_gid, this_weight in viewitems(normalized_delta_weights_dict):
                for syn_id in syn_ids_by_source_gid_dict[source_gid]:
                    output_syn_ids[i] = syn_id
                    output_weights[i] = this_weight
                    i += 1
            output_weights_dict[this_gid] = {'syn_id': output_syn_ids, synapse_name: output_weights}

            logger.info('Rank %i; destination: %s; gid %i; generated structured weights for %i inputs in %.2f '
                        's' % (rank, destination, this_gid, len(output_syn_ids), time.time() - local_time))
            gid_count += 1

        if iter_count % write_size == 0:
            gc.collect()
            if not dry_run:
                count = comm.reduce(len(output_weights_dict), op=MPI.SUM, root=0)
                append_cell_attributes(output_weights_path, destination, output_weights_dict,
                                       namespace=this_output_weights_namespace, comm=env.comm, io_size=env.io_size,
                                       chunk_size=chunk_size, value_chunk_size=value_chunk_size)
                if rank == 0:
                    logger.info('Destination: %s; appended weights for %i cells' % (destination, count))
            output_weights_dict.clear()
            gc.collect()

    if not dry_run:
        append_cell_attributes(output_weights_path, destination, output_weights_dict,
                               namespace=this_output_weights_namespace, comm=env.comm, io_size=env.io_size,
                               chunk_size=chunk_size, value_chunk_size=value_chunk_size)
        if rank == 0:
            count = comm.reduce(len(output_weights_dict), op=MPI.SUM, root=0)
            logger.info('Destination: %s; appended weights for %i cells' % (destination, count))

    global_count = comm.gather(gid_count, root=0)
    if rank == 0:
        logger.info('destination: %s; %i ranks assigned structured weights to %i cells in %.2f s' %
                    (destination, comm.size, np.sum(global_count), time.time() - start_time))

    MPI.Finalize()


if __name__ == '__main__':
    main(args=sys.argv[(utils.list_find(lambda x: os.path.basename(x) == os.path.basename(__file__), sys.argv)+1):])
