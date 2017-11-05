#!/bin/bash
#
#SBATCH -J repack_GC_forest
#SBATCH -o ./results/repack_GC_forest_syns.%j.o
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=16
#SBATCH -p shared
#SBATCH -t 12:00:00
#SBATCH --mail-user=ivan.g.raikov@gmail.com
#SBATCH --mail-type=END
#

module load hdf5

set -x
export prefix=/oasis/scratch/comet/iraikov/temp_project/dentate/Full_Scale_Control/
export input=$prefix/DGC_forest_syns_20171031.h5
export copy=$prefix/DGC_forest_syns_20171031_copy.h5
export output=$prefix/DGC_forest_syns_20171031_compressed.h5

h5repack -L -v -f GZIP=9 -i $copy -o $output




