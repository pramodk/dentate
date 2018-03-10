#!/bin/bash

# mpirun.mpich -np 2 python ./scripts/generate_distance_connections.py \
#  --config=./config/Full_Scale_Control.yaml \
#  --forest-path=./datasets/Test_GC_1000/DGC_forest_test_syns_20171019.h5 \
#  --connectivity-path=./datasets/Test_GC_1000/DG_test_connections_20171009.h5 \
#  --connectivity-namespace=Connections \
#  --coords-path=./datasets/dentate_Full_Scale_Control_coords_20171005.h5 \
#  --coords-namespace=Coordinates \
#  --io-size=1

mpirun.mpich -np 8 python ./scripts/generate_distance_connections.py \
 --config=./config/Full_Scale_Control.yaml --forest-path=./datasets/MC_forest_syns_20171206.h5 \
 --connectivity-path=./datasets/MC_connections_20180307.h5  --connectivity-namespace=Connections \
 --coords-path=./datasets/dentate_Full_Scale_Control_coords_20171005.h5 \
 --coords-namespace="Generated Coordinates" --io-size=3 --resample-volume=2 -v


# mpirun.mpich -np 8 python ./scripts/generate_distance_connections.py \
#   --config=./config/Full_Scale_Control.yaml \
#   --forest-path=./datasets/Test_GC_1000/BC_forest_syns_20180220.h5 \
#   --connectivity-path=./datasets/Test_GC_1000/BC_test_connections_20180307.h5 \
#   --connectivity-namespace=Connections \
#   --coords-path=./datasets/dentate_Full_Scale_Control_coords_20180214.h5 \
#   --coords-namespace="Generated Coordinates" \
#   --io-size=3 --resample-volume=2 -v

# mpirun.mpich -np 8 python ./scripts/generate_distance_connections.py \
#   --config=./config/Full_Scale_Control.yaml \
#   --forest-path=./datasets/AAC_forest_syns_20171102.h5 \
#   --connectivity-path=./datasets/Test_GC_1000/AAC_test_connections_20180307.h5 \
#   --connectivity-namespace=Connections \
#   --coords-path=./datasets/dentate_Full_Scale_Control_coords_20180214.h5 \
#   --coords-namespace="Generated Coordinates" \
#   --io-size=3 --resample-volume=2 -v