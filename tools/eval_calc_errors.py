# Author: Tomas Hodan (hodantom@cmp.felk.cvut.cz)
# Center for Machine Perception, Czech Technical University in Prague

# Calculates error of 6D object pose estimates.

import os
import sys
import glob
#import time

sys.path.append(os.path.abspath('..'))
from pysixd import inout, pose_error, misc
from params.dataset_params import get_dataset_params

# Results for which the errors will be calculated
#-------------------------------------------------------------------------------
result_base = '/home/tom/th_data/cmp/projects/sixd/sixd_results/'
# result_base = '/datagrid/6DB/sixd_results/'
result_paths = [
    result_base + 'hodan-iros15-forwacv17_tless_primesense'
]

# Other paths
#-------------------------------------------------------------------------------
# Mask of path to the output file with calculated errors
errors_mpath = '{result_path}_eval/{error_sign}/errors_{scene_id:02d}.yml'

# Parameters
#-------------------------------------------------------------------------------
# Top N pose estimates (with the highest score) to be evaluated for each
# object in each image
n_top = 1 # 0 = all estimates, -1 = given by the number of GT poses

# Pose error function
error_type = 'vsd' # 'vsd', 'adi', 'add', 'cou', 're', 'te'

# VSD parameters
vsd_delta = 15
vsd_tau = 20

# Error signature
error_sign = 'error=' + error_type + '_ntop=' + str(n_top)
if error_type == 'vsd':
    error_sign += '_delta=' + str(vsd_delta) + '_tau=' + str(vsd_tau)

# Error calculation
#-------------------------------------------------------------------------------
for result_path in result_paths:
    info = os.path.basename(result_path).split('_')
    method = info[0]
    dataset = info[1]
    test_type = info[2] if len(info) > 2 else ''

    # Select data type
    if dataset == 'tless':
        cam_type = test_type
        if error_type in ['adi', 'add']:
            model_type = 'cad_subdivided'
        else:
            model_type = 'cad'
    else:
        model_type = ''
        cam_type = ''

    # Load dataset parameters
    dp = get_dataset_params(dataset, model_type=model_type, test_type=test_type,
                            cam_type=cam_type)

    # Load object models
    if error_type in ['vsd', 'add', 'adi', 'cou']:
        print('Loading object models...')
        models = {}
        for obj_id in range(1, dp['obj_count'] + 1):
            models[obj_id] = inout.load_ply(dp['model_mpath'].format(obj_id))

    # Directories with results for individual scenes
    scene_dirs = sorted([d for d in glob.glob(os.path.join(result_path, '*'))
                         if os.path.isdir(d)])

    for scene_dir in scene_dirs:
        scene_id = int(os.path.basename(scene_dir))

        # Load info and GT poses for the current scene
        scene_info = inout.load_info(dp['scene_info_mpath'].format(scene_id))
        scene_gt = inout.load_gt(dp['scene_gt_mpath'].format(scene_id))

        res_paths = sorted(glob.glob(os.path.join(scene_dir, '*.yml')))
        errs = []
        im_id = -1
        depth_im = None
        for res_id, res_path in enumerate(res_paths):
            #t = time.time()

            # Parse image ID and object ID from the file name
            filename = os.path.basename(res_path).split('.')[0]
            im_id_prev = im_id
            im_id, obj_id = map(int, filename.split('_'))

            if res_id % 10 == 0:
                print('Calculating error: {}, {}, {}, {}, {}, {}, {}'.format(
                    error_type, method, dataset, test_type, scene_id,
                    im_id, obj_id))

            # Load depth image if VSD is selected
            if error_type == 'vsd' and im_id != im_id_prev:
                depth_path = dp['test_depth_mpath'].format(scene_id, im_id)
                depth_im = inout.load_depth(depth_path)
                depth_im *= dp['cam']['depth_scale'] # to [mm]

            # Load camera matrix
            if error_type in ['vsd', 'cou']:
                K = scene_info[im_id]['cam_K']

            # Load pose estimates
            res = inout.load_results_sixd17(res_path)
            ests = res['ests']

            # Sort the estimates by score (in descending order)
            ests_sorted = sorted(enumerate(ests), key=lambda x: x[1]['score'],
                                 reverse=True)

            # Select the required number of top estimated poses
            if n_top == 0: # All estimates are considered
                n_top_curr = None
            elif n_top == -1: # Given by the number of GT poses
                n_gt = sum([gt['obj_id'] == obj_id for gt in scene_gt[im_id]])
                n_top_curr = n_gt
            else:
                n_top_curr = n_top
            ests_sorted = ests_sorted[slice(0, n_top_curr)]

            for est_id, est in ests_sorted:
                est_errs = []
                R_e = est['R']
                t_e = est['t']

                errs_gts = {} # Errors w.r.t. GT poses of the same object
                for gt_id, gt in enumerate(scene_gt[im_id]):
                    if gt['obj_id'] != obj_id:
                        continue

                    e = -1.0
                    R_g = gt['cam_R_m2c']
                    t_g = gt['cam_t_m2c']

                    if error_type == 'vsd':
                        e = pose_error.vsd(R_e, t_e, R_g, t_g, models[obj_id],
                                           depth_im, vsd_delta, vsd_tau, K)
                    elif error_type == 'add':
                        e = pose_error.add(R_e, t_e, R_g, t_g, models[obj_id])
                    elif error_type == 'adi':
                        e = pose_error.adi(R_e, t_e, R_g, t_g, models[obj_id])
                    elif error_type == 'cou':
                        e = pose_error.cou(R_e, t_e, R_g, t_g, models[obj_id],
                                           dp['test_im_size'], K)
                    elif error_type == 're':
                        e = pose_error.re(R_e, R_g)
                    elif error_type == 'te':
                        e = pose_error.te(t_e, t_g)

                    errs_gts[gt_id] = e

                errs.append({
                    'im_id': im_id,
                    'obj_id': obj_id,
                    'est_id': est_id,
                    'score': est['score'],
                    'errors': errs_gts
                })
            #print('Evaluation time: {}s'.format(time.time() - t))

        print('Saving errors...')
        errors_path = errors_mpath.format(result_path=result_path,
                                          error_sign=error_sign,
                                          scene_id = scene_id)

        misc.ensure_dir(os.path.dirname(errors_path))
        inout.save_errors(errors_path, errs)

    print('')
print('Done.')
