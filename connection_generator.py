
import itertools
import numpy as np
import heapq
from mpi4py import MPI
from neuroh5.io import NeuroH5CellAttrGen, bcast_cell_attributes, read_population_ranges, append_graph
import click
import utils

try:
    import mkl
    mkl.set_num_threads(1)
except:
    pass


class ConnectionProb(object):
    """An object of this class will instantiate functions that describe
    the connection probabilities for each presynaptic population. These
    functions can then be used to get the distribution of connection
    probabilities across all possible source neurons, given the soma
    coordinates of a destination (post-synaptic) neuron.
    """
    def __init__(self, destination_population, soma_coords, ip_surface, extent, nstdev = 5.):
        """
        Warning: This method does not produce an absolute probability. It must be normalized so that the total area
        (volume) under the distribution is 1 before sampling.
        :param destination_population: post-synaptic population name
        :param soma_coords: a dictionary that contains per-population dicts of u, v coordinates of cell somas
        :param ip_surface: surface interpolation function, generated by e.g. BSplineSurface
        :param extent: dict: {source: 'width': (tuple of float), 'offset': (tuple of float)}
        """
        self.destination_population = destination_population
        self.soma_coords = soma_coords
        self.ip_surface  = ip_surface
        self.p_dist = {}
        self.width  = {}
        self.offset = {}
        self.sigma  = {}
        for source_population in extent:
            extent_width  = extent[source_population]['width']
            if extent[source_population].has_key('offset'):
                extent_offset = extent[source_population]['offset']
            else:
                extent_offset = None
            self.width[source_population] = {'u': extent_width[0], 'v': extent_width[1]}
            self.sigma[source_population] = {axis: self.width[source_population][axis] / nstdev / np.sqrt(2.) for axis in self.width[source_population]}
            if extent_offset is None:
                self.offset[source_population] = {'u': 0., 'v': 0.}
            else:
                self.offset[source_population] = {'u': extent_offset[source_population][0], 'v': extent_offset[source][1]}
            self.p_dist[source_population] = (lambda source_population: np.vectorize(lambda distance_u, distance_v:
                                                np.exp(-(((abs(distance_u) - self.offset[source_population]['u']) /
                                                            self.sigma[source_population]['u'])**2. +
                                                            ((abs(distance_v) - self.offset[source_population]['v']) /
                                                            self.sigma[source_population]['v'])**2.))))(source_population)
            

    def filter_by_arc_lengths(self, destination_gid, source_population, npoints=250):
        """
        Given the id of a target neuron, returns the arc distances along u and v
        and the gids of source neurons whose axons potentially contact the target neuron.
        :param destination_gid: int
        :param source_population: string
        :param soma_coords: nested dict of array
        :param npoints: number of points for arc length approximation [default: 250]
        :return: tuple of array of int
        """
        destination_coords = self.soma_coords[self.destination_population][destination_gid]
        destination_u = destination_coords['U Coordinate']
        destination_v = destination_coords['V Coordinate']
        source_soma_coords = soma_coords[source_population]:
        
        source_distance_u_lst = []
        source_distance_v_lst = []
        source_gid_lst        = []

        for (source_gid, coords_dict) in source_soma_coords.iteritems():

            source_u = coords_dict['U Coordinate']
            source_v = coords_dict['V Coordinate']
            
            U = np.linspace(destination_u, source_u, npoints)
            V = np.linspace(destination_v, source_v, npoints)

            source_distance_u = self.ip_surface.arc_length(U, destination_v)
            source_distance_v = self.ip_surface.arc_length(destination_u, V)

            if ((source_distance_u <= self.width[source]['u'] / 2. + self.offset[source]['u']) &
                 this_source_distance_v <= self.width[source]['v'] / 2. + self.offset[source]['v']):
                source_distance_u_lst.append(source_distance_u)
                source_distance_v_lst.append(source_distance_v)
                source_gid_lst.append(source_gid)

        return np.asarray(source_distance_u_lst), np.asarray(source_distance_v_lst), np.asarray(source_gid_lst)

    def get_prob(self, destination_gid, source, soma_coords, plot=False):
        """
        Given the soma coordinates of a destination neuron and a population source, return an array of connection 
        probabilities and an array of corresponding source gids.
        :param destination: string
        :param source: string
        :param destination_gid: int
        :param soma_coords: nested dict of array
        :param distance_U: array of float
        :param distance_V: array of float
        :param plot: bool
        :return: array of float, array of int
        """
        source_distance_u, source_distance_v, source_gid = self.filter_by_arc_lengths(destination_gid, source)
        p = self.p_dist[source](source_distance_u, source_distance_v)
        p /= np.sum(p)
        if plot:
            plt.scatter(source_distance_u, source_distance_v, c=p)
            plt.title(source+' -> '+target)
            plt.xlabel('Septotemporal distance (um)')
            plt.ylabel('Transverse distance (um)')
            plt.show()
            plt.close()
        return p, source_gid

def filter_projections (syn_layer, swc_type, syn_type, projection_synapse_dict, projection_prob_dict):
    {k: projection_prob_dict[k] for k,v in projection_synapse_dict.iteritems() if (syn_layer in v[0]) and (swc_type in v[1]) and (syn_type in v[2])}
    
def generate_synaptic_connections(synapse_dict, projection_synapse_dict, projection_prob_dict):
    """
    :param synapse_dict:
    :param projection_synapse_dict:
    :param projection_prob_dict:
    """
    syn_id_lst = []
    source_gid_lst = []
    for (syn_id,syn_type,swc_type,syn_layer) in itertools.izip(synapse_dict['syn_ids'],
                                                               synapse_dict['syn_types'],
                                                               synapse_dict['swc_types'],
                                                               synapse_dict['syn_layers']):
        candidate_connections = filter_projections(syn_type, swc_type, syn_layer, projection_synapse_dict, projection_prob_dict)
        while True:
            for (source_population, h) in candidate_connections.iteritems():
            ## choose random number / compare with prob of top heap element
            ## if random > top heap elem:
            ##    add to syn_id_lst and source_gid_lst
            ##    remove top heap elem
            ##    break loop

def generate_uv_distance_connections(comm, 
                                     connection_prob, forest_path,
                                     synapse_layers, synapse_types,
                                     synapse_locations, synapse_namespace, 
                                     connectivity_seed, connectivity_namespace,
                                     io_size, chunk_size, value_chunk_size, cache_size):
    """
    :param comm:
    :param connection_prob:
    :param forest_path:
    :param synapse_layers:
    :param synapse_types:
    :param synapse_locations:
    :param synapse_namespace:
    :param synapse_seed:
    :param connectivity_namespace:
    :param io_size:
    :param chunk_size:
    :param value_chunk_size:
    :param cache_size:
    """
    rank = comm.rank  # The process ID (integer 0-3 for 4-process run)

    if io_size == -1:
        io_size = comm.size
    if rank == 0:
        print '%i ranks have been allocated' % comm.size
    sys.stdout.flush()

    start_time = time.time()

    destination_population = connection_prob.destination_population

    projection_synapse_dict = {source_population: (set(synapse_layers[destination_population][source_population]),
                                                   set(synapse_locations[destination_population][source_population]),
                                                   set(synapse_types[destination_population][source_population]))
                                for source_population in source_populations}

    count = 0
    for destination_gid, attributes_dict in NeuroH5CellAttrGen(comm, forest_path, destination, io_size=io_size,
                                                               cache_size=cache_size, namespace=synapse_namespace):
        last_time = time.time()
        
        connection_dict = {}
        p_dict          = {}

        if destination_gid is None:
            print 'Rank %i destination gid is None' % rank
        else:
            print 'Rank %i received attributes for destination: %s, gid: %i' % (rank, destination, destination_gid)
            local_np_random.seed(destination_gid + connectivity_seed)
            synapse_dict   = attributes_dict[synapse_namespace]
            syn_id_dict    = {}

            projection_prob_dict = {}
            for source_population in source_populations:
                h = []
                probs, source_gids = connection_prob.get_prob(destination_gid, source_population)
                for (prob, source_gid) in itertools.izip(probs, source_gids):
                    heapq.heappush(h, (prob, source_gid))
                connection_prob_dict[source_population] = h

            syn_id_lst, source_gid_lst = generate_synaptic_connections(synapse_dict, projection_synapse_dict, projection_prob_dict)
            
            count += len(syn_id_lst)
            
            connection_dict[destination_gid] = {}
            connection_dict[destination_gid]['source_gid'] = np.asarray(source_gid_lst, dtype='uint32')
            connection_dict[destination_gid]['syn_id']     = np.asarray(syn_id_lst, dtype='uint32')
            print 'Rank %i took %i s to compute connectivity for destination: %s, gid: %i' % (rank, time.time() - last_time,
                                                                                         destination, destination_gid)
            sys.stdout.flush()
        last_time = time.time()
        append_graph(comm, connectivity_path, source, destination, connection_dict, io_size=io_size)
        if rank == 0:
            print 'Appending connectivity for destination: %s took %i s' % (destination, time.time() - last_time)
        sys.stdout.flush()
        del connection_dict
        del p_dict
        gc.collect()

    global_count = comm.gather(count, root=0)
    if rank == 0:
        print '%i ranks took took %i s to compute connectivity for %i cells' % (comm.size, time.time() - start_time,
                                                                                np.sum(global_count))


