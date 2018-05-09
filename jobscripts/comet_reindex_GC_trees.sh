#!/bin/bash
#
#SBATCH -J reindex_GC_trees
#SBATCH -o ./results/reindex_GC_trees.%j.o
#SBATCH --nodes=32
#SBATCH --ntasks-per-node=24
#SBATCH -t 3:00:00
#SBATCH --mail-user=ivan.g.raikov@gmail.com
#SBATCH --mail-type=END
#SBATCH --mail-type=BEGIN
#


module load python
module load hdf5
module load scipy
module load mpi4py

export PYTHONPATH=/share/apps/compute/mpi4py/mvapich2_ib/lib/python2.7/site-packages:/opt/python/lib/python2.7/site-packages:$PYTHONPATH
export PYTHONPATH=$HOME/bin/nrnpython/lib/python:$PYTHONPATH
export PYTHONPATH=$HOME/model:$HOME/model/dentate/btmorph:$PYTHONPATH
export SCRATCH=/oasis/scratch/comet/iraikov/temp_project
export LD_PRELOAD=$MPIHOME/lib/libmpi.so

set -x

ibrun -np 768 python ./scripts/reindex_trees.py \
    --population=GC \
    --forest-path=$SCRATCH/dentate/Full_Scale_Control/DGC_forest_extended_compressed_20180224.h5 \
    --output-path=$SCRATCH/dentate/Full_Scale_Control/DGC_forest_reindex_20180418.h5 \
    --index-path=$SCRATCH/dentate/Full_Scale_Control/dentate_GC_coords_20180418.h5 \
    --io-size=24 -v
