
import sys, gc, os
from mpi4py import MPI
import click
import dentate
from dentate import utils, plot


@click.command()
@click.option("--connectivity-path", '-p', required=True, type=click.Path())
@click.option("--coords-path", '-c', required=True, type=click.Path())
@click.option("--vertex-metrics-namespace", type=str, default='Vertex Metrics')
@click.option("--distances-namespace", '-t', type=str, default='Arc Distances')
@click.option("--destination", '-d', type=str)
@click.option("--sources", '-s', type=str, multiple=True)
@click.option("--normed", type=bool, default=False, is_flag=True)
@click.option("--metric", '-m', type=str, default='Indegree')
@click.option("--graph-type", type=str, default='histogram2d')
@click.option("--bin-size", type=float, default=50.)
@click.option("--font-size", type=float, default=14)
@click.option("--verbose", "-v", type=bool, default=False, is_flag=True)
def main(connectivity_path, coords_path, vertex_metrics_namespace, distances_namespace, destination, sources, normed, metric, graph_type, bin_size, font_size, verbose):
        
    utils.config_logging(verbose)
    logger = utils.get_script_logger(os.path.basename(__file__))

    plot.plot_vertex_metrics (connectivity_path, coords_path, vertex_metrics_namespace, distances_namespace,
                              destination, sources, metric=metric, normed=normed, binSize=bin_size,
                              fontSize=font_size, graphType=graph_type, saveFig=True)

if __name__ == '__main__':
    main(args=sys.argv[(utils.list_find(lambda x: os.path.basename(x) == os.path.basename(__file__), sys.argv)+1):])



    
