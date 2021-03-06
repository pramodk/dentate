%
% Place cell rate map generator
%


W = 200.0; % linear track length, cm
H = 200.0; % 
N = 85000; % Approximately reflecting Layer II LEC cells in the rat
M = 1;
lambda_range = [W*2, W*2];
grid_unit = 9;

seed = 22;

[X,Y,lambda,theta,xoff,yoff] = init_network(W, H, M, N, lambda_range, 20, grid_unit, seed);
ratemap  = place_ratemap(X,Y,lambda,theta,xoff,yoff);

place_data.W = W;
place_data.H = 0;
place_data.M = M;
place_data.N = N;
place_data.X = X;
place_data.Y = Y;
place_data.lambda = lambda;
place_data.theta = theta;
place_data.xoff = xoff;
place_data.yoff = yoff;

save('-v7.3','ec2_place_ratemap.mat','ratemap');
save('-v7.3','ec2_place_data.mat','place_data');


