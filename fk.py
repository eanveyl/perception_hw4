import os, argparse, json
import numpy as np

from scipy.spatial.transform import Rotation as R

# for simulator
import pybullet as p

# for geometry information
from utils.bullet_utils import draw_coordinate, get_matrix_from_pose, get_pose_from_matrix

SIM_TIMESTEP = 1.0 / 240.0
JACOBIAN_SCORE_MAX = 10.0
JACOBIAN_ERROR_THRESH = 0.05
FK_SCORE_MAX = 10.0
FK_ERROR_THRESH = 0.005
TASK1_SCORE_MAX = JACOBIAN_SCORE_MAX + FK_SCORE_MAX

def cross(a : np.ndarray, b : np.ndarray) -> np.ndarray :
    return np.cross(a, b)

def get_panda_DH_params():

    # TODO: this is the DH parameters (follwing Craig's convention) of the robot in this assignment,
    # It will be a little bit different from the official spec 
    # You need to use these parameters to compute the forward kinematics and Jacobian matrix
    # details : 
    # see "pybullet_robot_envs/panda_envs/robot_data/franka_panda/panda_model.urdf" in this project folder
    # official spec : https://frankaemika.github.io/docs/control_parameters.html#denavithartenberg-parameters
    
    dh_params = [
        {'a':  0,      'd': 0.333, 'alpha':  0,  }, # panda_joint1
        {'a':  0,      'd': 0,     'alpha': -np.pi/2}, # panda_joint2
        {'a':  0,      'd': 0.316, 'alpha':  np.pi/2}, # panda_joint3
        {'a':  0.0825, 'd': 0,     'alpha':  np.pi/2}, # panda_joint4
        {'a': -0.0825, 'd': 0.384, 'alpha': -np.pi/2}, # panda_joint5
        {'a':  0,      'd': 0,     'alpha':  np.pi/2}, # panda_joint6
        {'a':  0.088,  'd': 0.07,  'alpha':  np.pi/2}, # panda_joint7
    ]

    return dh_params

def get_transform_to_base_from(level: int, pose: list, DH_params: dict, use_inclusive_range: bool=False) -> np.matrix:
    """
        This function is so complicated because it calculates the T for either all the joints, meaning from 0 <- E, 
        and at the same time, it must be able to compute the transformation T from any point of reference towards 0.
    """
    
    T = np.matrix(np.identity(4))

    if level != len(DH_params):
        use_inclusive_range = True
        
    for i in range(level):
        cos_th_i = np.cos(pose[i])
        sin_th_i = np.sin(pose[i])
        a_i = DH_params[i]["a"]
        cos_alpha_i = np.cos(DH_params[i]["alpha"])
        sin_alpha_i = np.sin(DH_params[i]["alpha"])
        d_i = DH_params[i]["d"]

        # modified DH convention
        T = T @ np.matrix([[cos_th_i, -1*sin_th_i, 0, a_i],
                [sin_th_i*cos_alpha_i, cos_th_i*cos_alpha_i, -1*sin_alpha_i, -1*d_i*sin_alpha_i],
                [sin_th_i*sin_alpha_i, cos_th_i*sin_alpha_i, cos_alpha_i, d_i*cos_alpha_i], 
                [0,0,0,1]])

    if use_inclusive_range:
        # use this because range(0) won't calculate anything
        # this case will be ran every time the desired transform is not 
        # the full one from base to last joint, but only a 
        # part from it
        cos_th_i = np.cos(pose[level])
        sin_th_i = np.sin(pose[level])
        a_i = DH_params[level]["a"]
        cos_alpha_i = np.cos(DH_params[level]["alpha"])
        sin_alpha_i = np.sin(DH_params[level]["alpha"])
        d_i = DH_params[level]["d"]

        # modified DH convention
        T = T @ np.matrix([[cos_th_i, -1*sin_th_i, 0, a_i],
                [sin_th_i*cos_alpha_i, cos_th_i*cos_alpha_i, -1*sin_alpha_i, -1*d_i*sin_alpha_i],
                [sin_th_i*sin_alpha_i, cos_th_i*sin_alpha_i, cos_alpha_i, d_i*cos_alpha_i], 
                [0,0,0,1]])

    return T

def calc_Z(l: int, q: np.ndarray, DH_params: dict, base_pose: np.ndarray) -> np.matrix:
    Z = (base_pose @ get_transform_to_base_from(l, q, DH_params))[:3,:3] @ np.matrix([[0],
                                                                                    [0],
                                                                                    [1]])
    return Z

def calc_P(l: int, q: np.ndarray, n_joints: int, DH_params: dict, base_pose: np.ndarray) -> np.matrix:
    P_0E = base_pose @ get_transform_to_base_from(n_joints, q, DH_params) @ np.matrix([[0],
                                                                                    [0],
                                                                                    [0],
                                                                                    [1]])

    P_0_from_i_1 = base_pose @ get_transform_to_base_from(l, q, DH_params) @ np.matrix([[0],
                                                                                    [0],
                                                                                    [0],
                                                                                    [1]])

    P = P_0E - P_0_from_i_1

    return P[0:3,0]

def construct_jacobian(n_joints: int, q: np.ndarray, DH_params: dict, base_pose: np.ndarray) -> np.matrix:
    J = np.matrix(np.zeros((6,n_joints)))

    for i in range(n_joints):
        Z = calc_Z(i, q, DH_params, base_pose)
        P = calc_P(i, q, n_joints, DH_params, base_pose)

        J_Li = np.cross(np.squeeze(Z), np.squeeze(P))
        J_Ai = np.squeeze(Z)

        J[:,i] = np.vstack((J_Li.T,J_Ai.T))
    
    return J

def your_fk(robot, DH_params : dict, q : list or tuple or np.ndarray) -> np.ndarray:

    # robot initial position
    base_pos = robot._base_position
    base_pose = list(base_pos) + [0, 0, 0, 1]  

    assert len(DH_params) == 7 and len(q) == 7, f'Both DH_params and q should contain 7 values,\n' \
                                                f'but get len(DH_params) = {DH_params}, len(q) = {len(q)}'

    A = get_matrix_from_pose(base_pose) # a 4x4 matrix, type should be np.ndarray
    jacobian = np.zeros((6, 7)) # a 6x7 matrix, type should be np.ndarray

    # -------------------------------------------------------------------------------- #
    # --- TODO: Read the task description                                          --- #
    # --- Task 1 : Compute Forward-Kinematic and Jacobian of the robot by yourself --- #
    # ---          Try to implement `your_fk` function without using any pybullet  --- #
    # ---          API. (20% for accuracy)                                         --- #
    # -------------------------------------------------------------------------------- #
    
    #### your code ####

    # A = ? # may be more than one line
    A = A @ get_transform_to_base_from(7, q, DH_params)
        
    # jacobian = ? # may be more than one line
    n_joints = len(DH_params)
    jacobian = construct_jacobian(n_joints, q, DH_params, get_matrix_from_pose(base_pose))    

    # -45 degree adjustment along z axis
    # details : see "pybullet_robot_envs/panda_envs/robot_data/franka_panda/panda_model.urdf"
    adjustment = R.from_rotvec([0, 0, -0.785398163397]).as_matrix() # Don't touch
    A[:3, :3] = A[:3, :3] @ adjustment # Don't touch

    ###################

    pose_7d = np.asarray(get_pose_from_matrix(A))

    return pose_7d, jacobian

# TODO: [for your information]
# This function is the scoring function, we will use the same code 
# to score your algorithm using all the testcases
def score_fk(robot, testcase_files : str, visualize : bool=False):

    testcase_file_num = len(testcase_files)
    dh_params = get_panda_DH_params()
    fk_score = [FK_SCORE_MAX / testcase_file_num for _ in range(testcase_file_num)]
    fk_error_cnt = [0 for _ in range(testcase_file_num)]
    jacobian_score = [JACOBIAN_SCORE_MAX / testcase_file_num for _ in range(testcase_file_num)]
    jacobian_error_cnt = [0 for _ in range(testcase_file_num)]

    p.addUserDebugText(text = "Scoring Your Forward Kinematic Algorithm ...", 
                        textPosition = [0.1, -0.6, 1.5],
                        textColorRGB = [1,1,1],
                        textSize = 1.0,
                        lifeTime = 0)

    print("============================ Task 1 : Forward Kinematic ============================\n")
    for file_id, testcase_file in enumerate(testcase_files):

        f_in = open(testcase_file, 'r')
        fk_dict = json.load(f_in)
        f_in.close()
        
        test_case_name = os.path.split(testcase_file)[-1]

        joint_poses = fk_dict['joint_poses']
        poses = fk_dict['poses']
        jacobians = fk_dict['jacobian']

        cases_num = len(fk_dict['joint_poses'])

        penalty = (TASK1_SCORE_MAX / testcase_file_num) / (0.3 * cases_num)

        for i in range(cases_num):
            your_pose, your_jacobian = your_fk(robot, dh_params, joint_poses[i])
            gt_pose = poses[i]

            if visualize :
                color_yours = [[1,0,0], [1,0,0], [1,0,0]]
                color_gt = [[0,1,0], [0,1,0], [0,1,0]]
                draw_coordinate(your_pose, size=0.01, color=color_yours)
                draw_coordinate(gt_pose, size=0.01, color=color_gt)

            fk_error = np.linalg.norm(your_pose - np.asarray(gt_pose), ord=2)
            print("Your pose=\n", your_pose)
            print("GT pose=\n", gt_pose)
            if fk_error > FK_ERROR_THRESH:
                fk_score[file_id] -= penalty
                fk_error_cnt[file_id] += 1

            print("Your jacobian=\n", your_jacobian)
            print("GT jacobian=\n", jacobians[i])
            jacobian_error = np.linalg.norm(your_jacobian - np.asarray(jacobians[i]), ord=2)
            if jacobian_error > JACOBIAN_ERROR_THRESH:
                jacobian_score[file_id] -= penalty
                jacobian_error_cnt[file_id] += 1
        
        fk_score[file_id] = 0.0 if fk_score[file_id] < 0.0 else fk_score[file_id]
        jacobian_score[file_id] = 0.0 if jacobian_score[file_id] < 0.0 else jacobian_score[file_id]

        score_msg = "- Testcase file : {}\n".format(test_case_name) + \
                    "- Your Score Of Forward Kinematic : {:00.03f} / {:00.03f}, Error Count : {:4d} / {:4d}\n".format(
                            fk_score[file_id], FK_SCORE_MAX / testcase_file_num, fk_error_cnt[file_id], cases_num) + \
                    "- Your Score Of Jacobian Matrix   : {:00.03f} / {:00.03f}, Error Count : {:4d} / {:4d}\n".format(
                            jacobian_score[file_id], JACOBIAN_SCORE_MAX / testcase_file_num, jacobian_error_cnt[file_id], cases_num)
        
        print(score_msg)
    p.removeAllUserDebugItems()

    total_fk_score = 0.0
    total_jacobian_score = 0.0
    for file_id in range(testcase_file_num):
        total_fk_score += fk_score[file_id]
        total_jacobian_score += jacobian_score[file_id]
    
    print("====================================================================================")
    print("- Your Total Score : {:00.03f} / {:00.03f}".format(
        total_fk_score + total_jacobian_score, FK_SCORE_MAX + JACOBIAN_SCORE_MAX))
    print("====================================================================================")

def main(args):

    # ------------------------ #
    # --- Setup simulation --- #
    # ------------------------ #

    # Create pybullet env without GUI
    visualize = args.gui
    physics_client_id = p.connect(p.GUI if visualize else p.DIRECT)
    p.configureDebugVisualizer(p.COV_ENABLE_GUI,0)
    p.resetDebugVisualizerCamera(
        cameraDistance=0.5,
        cameraYaw=90,
        cameraPitch=0,
        cameraTargetPosition=[0.7, 0.0, 1.0]
    )
    p.resetSimulation()
    p.setPhysicsEngineParameter(numSolverIterations=150)

    # ------------------- #
    # --- Setup robot --- #
    # ------------------- #

    # goto initial pose
    from pybullet_robot_envs.panda_envs.panda_env import pandaEnv
    robot = pandaEnv(physics_client_id, use_IK=1)

    # -------------------------------------------- #
    # --- Test your Forward Kinematic function --- #
    # -------------------------------------------- #

    testcase_files = [
        'test_case/fk_testcase.json',
        # 'test_case/fk_testcase_ta.json' # only available for TAs
    ]

    # scoring your algorithm
    score_fk(robot, testcase_files, visualize=args.visualize_pose)


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--gui', '-g', action='store_true', default=False, help='gui : whether show the window')
    parser.add_argument('--visualize-pose', '-vp', action='store_true', default=False, help='whether show the poses of end effector')
    args = parser.parse_args()
    main(args)