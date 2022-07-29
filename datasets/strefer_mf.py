import os
import torch
import numpy as np
from torch.utils.data import Dataset
import json
from utils import pc_utils, strefer_utils
from utils.metrics import cal_accuracy
from pytorch_transformers.tokenization_bert import BertTokenizer
import cv2
from tqdm import tqdm
import math
import cmath

class STREFER_MF(Dataset):
    def __init__(self, args, split):
        super().__init__()
        self.split = split
        self.base_path = args.data_path
        if split == 'train':
            self.data_path = os.path.join('data/train_SHTpersonRefer_ann.json')
        else:
            self.data_path = os.path.join('data/test_SHTpersonRefer_ann.json')
        self.dataset = json.load(open(self.data_path, 'r'))
        self.sample_points_num = args.sample_points_num
        self.x_size, self.y_size = args.img_shape
        self.tokenizer = BertTokenizer.from_pretrained(args.bert_model)

        self.data_type = torch.float32

        self.use_view = args.use_view
        self.use_vel = args.use_vel
        self.use_xyz = True if not self.use_view and not self.use_vel else False
        self.use_rgb = not args.no_rgb
        self.dim = 23 if self.use_rgb else 4

        self.xmin, self.ymin, self.zmin, self.xmax, self.ymax, self.zmax = (0, -20.48, -4, 30.72, 20.48, 1)
        self.rmin, self.rmax = (-math.pi, math.pi)
        self.vmin, self.vmax = (0, 3)
        self.lmin, self.wmin, self.hmin = (0, 0, 0)
        self.lmax = self.xmax - self.xmin
        self.wmax = self.ymax - self.ymin
        self.hmax = self.zmax - self.zmin
        self.volume = self.lmax * self.wmax * self.hmax

        self.target_threshold = args.threshold
        self.rel_threshold = args.rel_dist_threshold

        self.spatial_dim = 8
        if args.use_view:
            self.spatial_dim = 7
        if args.use_vel:
            self.spatial_dim = 9
    

    def __getitem__(self, index):
        data = self.dataset[index]

        group_id = data['group_id']
        scene_id = data['scene_id']

        point_cloud_info = data['point_cloud']
        image_info = data['image']
        language_info = data['language']
        previous_info = data['previous']

        # read image
        image_name = image_info['image_name']
        image_path = os.path.join(self.base_path, group_id, scene_id, 'left', image_name)

        image = strefer_utils.load_image(image_path)
        img_y_size, img_x_size, dim = image.shape
        image = cv2.resize(image, (self.x_size, self.y_size))
        image = image.transpose((2, 0, 1))

        prev_image_name = previous_info['image_name']
        prev_image_path = os.path.join(self.base_path, group_id, scene_id, 'left', prev_image_name)
        prev_image = strefer_utils.load_image(prev_image_path)
        prev_img_y_size, prev_img_x_size, prev_dim = prev_image.shape
        prev_image = cv2.resize(prev_image, (self.x_size, self.y_size))
        prev_image = prev_image.transpose((2, 0, 1))

        # read points
        point_cloud_name = point_cloud_info['point_cloud_name']
        prev_point_cloud_name = previous_info['point_cloud_name']
        if self.use_rgb:
            point_cloud_path = os.path.join(self.base_path, group_id, scene_id, 'bin_painting_seg_feature', point_cloud_name)
            points = np.fromfile(point_cloud_path, dtype=np.float32).reshape(-1, self.dim)
            prev_point_cloud_path = os.path.join(self.base_path, group_id, scene_id, 'bin_painting_seg_feature', prev_point_cloud_name)
            prev_points = np.fromfile(prev_point_cloud_path, dtype=np.float32).reshape(-1, self.dim)
        else:
            point_cloud_path = os.path.join(self.base_path, group_id, scene_id, 'bin_v1', point_cloud_name)
            points = np.fromfile(point_cloud_path, dtype=np.float32).reshape(-1, self.dim)
            prev_point_cloud_path = os.path.join(self.base_path, group_id, scene_id, 'bin_v1', prev_point_cloud_name)
            prev_points = np.fromfile(prev_point_cloud_path, dtype=np.float32).reshape(-1, self.dim)

        # spatial
        boxes3d = np.load(f"data/pred_bboxes/{group_id}/{scene_id}/{point_cloud_name[:-4]}.npy")
        objects_pc = strefer_utils.batch_extract_pc_in_box3d(points, boxes3d, self.sample_points_num, self.dim)
        corners2d = strefer_utils.batch_compute_box_3d(boxes3d)
        object_center = boxes3d[:, :3]

        prev_boxes3d = np.load(f"data/pred_bboxes/{group_id}/{scene_id}/{prev_point_cloud_name[:-4]}.npy")
        prev_objects_pc = strefer_utils.batch_extract_pc_in_box3d(prev_points, prev_boxes3d, self.sample_points_num, self.dim)
        prev_corners2d = strefer_utils.batch_compute_box_3d(prev_boxes3d)
        prev_object_center = prev_boxes3d[:, :3]

        spatial = []
        prev_spatial = []
        if self.use_xyz is True:
            max_value = np.array([self.xmax, self.ymax, self.zmax, self.lmax, self.wmax, self.hmax, self.rmax])
            min_value = np.array([self.xmin, self.ymin, self.zmin, self.lmin, self.wmin, self.hmin, self.rmin])
            for i in range(len(boxes3d)):
                x, y, z, l, w, h, r = strefer_utils.norm(boxes3d[i][:7], min_value, max_value)
                volume = (boxes3d[i][3] * boxes3d[i][4] * boxes3d[i][5]) /self.volume
                spatial.append([x, y, z, l, w, h, r, volume])
            for i in range(len(prev_boxes3d)):
                x, y, z, l, w, h, r = strefer_utils.norm(prev_boxes3d[i][:7], min_value, max_value)
                volume = (prev_boxes3d[i][3] * prev_boxes3d[i][4] * prev_boxes3d[i][5]) /self.volume
                prev_spatial.append([x, y, z, l, w, h, r, volume])
        elif self.use_vel is True:
            for i in range(len(boxes3d)):
                x, _, _, _, _, _, r, xvel, yvel = boxes3d[i][:9]
                x = strefer_utils.norm(x, self.xmin, self.xmax)
                r = strefer_utils.norm(r, self.rmin, self.rmax)
                vel, drt = cmath.polar(complex(xvel, yvel))
                vel = strefer_utils.norm(vel, self.vmin, self.vmax)
                drt = strefer_utils.norm(drt, self.rmin, self.rmax)
                eachbox_2d = corners2d[i]
                eachbox_2d[:, 0][eachbox_2d[:, 0]<0] = 0
                eachbox_2d[:, 0][eachbox_2d[:, 0]>=img_x_size] = img_x_size-1
                eachbox_2d[:, 1][eachbox_2d[:, 1]<0] = 0
                eachbox_2d[:, 1][eachbox_2d[:, 1]>=img_y_size] = img_y_size-1
                xmin, ymin = eachbox_2d.min(axis=0)
                xmax, ymax = eachbox_2d.max(axis=0)
                square = (ymax - ymin) * (xmax - xmin) / (img_x_size * img_y_size)
                xmin /= img_x_size
                xmax /= img_x_size
                ymin /= img_y_size
                ymax /= img_y_size
                spatial.append([xmin, ymin, xmax, ymax, x, r, square, vel, drt])
            for i in range(len(prev_boxes3d)):
                x, _, _, _, _, _, r, xvel, yvel = prev_boxes3d[i][:9]
                x = strefer_utils.norm(x, self.xmin, self.xmax)
                r = strefer_utils.norm(r, self.rmin, self.rmax)
                vel, drt = cmath.polar(complex(xvel, yvel))
                vel = strefer_utils.norm(vel, self.vmin, self.vmax)
                drt = strefer_utils.norm(drt, self.rmin, self.rmax)
                eachbox_2d = prev_corners2d[i]
                eachbox_2d[:, 0][eachbox_2d[:, 0]<0] = 0
                eachbox_2d[:, 0][eachbox_2d[:, 0]>=prev_img_x_size] = prev_img_x_size-1
                eachbox_2d[:, 1][eachbox_2d[:, 1]<0] = 0
                eachbox_2d[:, 1][eachbox_2d[:, 1]>=prev_img_y_size] = prev_img_y_size-1
                xmin, ymin = eachbox_2d.min(axis=0)
                xmax, ymax = eachbox_2d.max(axis=0)
                square = (ymax - ymin) * (xmax - xmin) / (prev_img_x_size * prev_img_y_size)
                xmin /= prev_img_x_size
                xmax /= prev_img_x_size
                ymin /= prev_img_y_size
                ymax /= prev_img_y_size
                prev_spatial.append([xmin, ymin, xmax, ymax, x, r, square, vel, drt])
        elif self.use_view is True:
            for i in range(len(boxes3d)):
                eachbox_2d = corners2d[i]
                x, _, _, _, _, _, r = boxes3d[i][:7]
                x = strefer_utils.norm(x, self.xmin, self.xmax)
                r = strefer_utils.norm(r, self.rmin, self.rmax)
                eachbox_2d = corners2d[i]
                eachbox_2d[:, 0][eachbox_2d[:, 0]<0] = 0
                eachbox_2d[:, 0][eachbox_2d[:, 0]>=img_x_size] = img_x_size-1
                eachbox_2d[:, 1][eachbox_2d[:, 1]<0] = 0
                eachbox_2d[:, 1][eachbox_2d[:, 1]>=img_y_size] = img_y_size-1
                xmin, ymin = eachbox_2d.min(axis=0)
                xmax, ymax = eachbox_2d.max(axis=0)
                square = (ymax - ymin) * (xmax - xmin) / (img_x_size * img_y_size)
                xmin /= img_x_size
                xmax /= img_x_size
                ymin /= img_y_size
                ymax /= img_y_size
                spatial.append([xmin, ymin, xmax, ymax, x, r, square])
            for i in range(len(prev_boxes3d)):
                x, _, _, _, _, _, r = prev_boxes3d[i][:7]
                x = strefer_utils.norm(x, self.xmin, self.xmax)
                r = strefer_utils.norm(r, self.rmin, self.rmax)
                eachbox_2d = prev_corners2d[i]
                eachbox_2d[:, 0][eachbox_2d[:, 0]<0] = 0
                eachbox_2d[:, 0][eachbox_2d[:, 0]>=prev_img_x_size] = prev_img_x_size-1
                eachbox_2d[:, 1][eachbox_2d[:, 1]<0] = 0
                eachbox_2d[:, 1][eachbox_2d[:, 1]>=prev_img_y_size] = prev_img_y_size-1
                xmin, ymin = eachbox_2d.min(axis=0)
                xmax, ymax = eachbox_2d.max(axis=0)
                square = (ymax - ymin) * (xmax - xmin) / (prev_img_x_size * prev_img_y_size)
                xmin /= prev_img_x_size
                xmax /= prev_img_x_size
                ymin /= prev_img_y_size
                ymax /= prev_img_y_size
                prev_spatial.append([xmin, ymin, xmax, ymax, x, r, square])
        else:
            raise NotImplementedError
        spatial = np.array(spatial, dtype=np.float32)
        prev_spatial = np.array(prev_spatial, dtype=np.float32)

        # bboxes2d
        boxes2d = []
        for box in corners2d:
            xmin, ymin = box.min(axis=0)
            xmax, ymax = box.min(axis=0)
            xmin = int(xmin * self.x_size / img_x_size)
            xmax = int(xmax * self.x_size / img_x_size)
            ymin = int(ymin * self.y_size / img_y_size)
            ymax = int(ymax * self.y_size / img_y_size)
            boxes2d.append([xmin, ymin, xmax, ymax])
        boxes2d = np.array(boxes2d)
    
        prev_boxes2d = []
        for box in prev_corners2d:
            xmin, ymin = box.min(axis=0)
            xmax, ymax = box.min(axis=0)
            xmin = int(xmin * self.x_size / prev_img_x_size)
            xmax = int(xmax * self.x_size / prev_img_x_size)
            ymin = int(ymin * self.y_size / prev_img_y_size)
            ymax = int(ymax * self.y_size / prev_img_y_size)
            prev_boxes2d.append([xmin, ymin, xmax, ymax])
        prev_boxes2d = np.array(prev_boxes2d)

        # target
        target = np.zeros((len(boxes3d), ), dtype=np.float32)
        target_box = np.array(point_cloud_info['bbox'], dtype=np.float32)
        for i, box in enumerate(boxes3d):
            iou = pc_utils.cal_iou3d(target_box, box)
            target[i] = 1 if iou >= self.target_threshold else 0

        # token
        sentence = language_info['description'].lower()
        sentence = "[CLS] " + sentence + " [SEP]"
        token = self.tokenizer.encode(sentence)

        # relative distance
        rel_dist_mask = np.zeros((len(object_center), len(prev_object_center)), dtype=np.bool)
        for i in range(rel_dist_mask.shape[0]):
            obj_pos = object_center[i]
            for j in range(rel_dist_mask.shape[1]):
                prev_obj_pos = prev_object_center[j]
                dist = np.sqrt(np.power(obj_pos - prev_obj_pos, 2).sum())
                if dist < self.rel_threshold:
                    rel_dist_mask[i, j] = 1

        return image, boxes2d, objects_pc, spatial, token, target, prev_image, prev_boxes2d, prev_objects_pc, prev_spatial, rel_dist_mask
    
    def collate_fn(self, raw_batch):
        raw_batch = list(zip(*raw_batch))

        # image  & prev_image
        image_list = raw_batch[0]
        image = []
        for img in image_list:
            img = torch.tensor(img, dtype=self.data_type)
            image.append(img)
        image = torch.stack(image, dim=0)

        prev_image_list = raw_batch[6]
        prev_image = []
        for img in prev_image_list:
            img = torch.tensor(img, dtype=self.data_type)
            prev_image.append(img)
        prev_image = torch.stack(prev_image, dim=0)

        # boxes2d & prev_boxes2d
        boxes2d_list = raw_batch[1]
        max_obj_num = 0
        for each_boxes2d in boxes2d_list:
            max_obj_num = max(max_obj_num, each_boxes2d.shape[0])
        prev_boxes2d_list = raw_batch[7]
        for each_boxes2d in prev_boxes2d_list:
            max_obj_num = max(max_obj_num, each_boxes2d.shape[0])
        
        boxes2d = torch.zeros((len(boxes2d_list), max_obj_num, 4), dtype=self.data_type)
        vis_mask = torch.zeros((len(boxes2d_list), max_obj_num), dtype=torch.long)
        for i, each_boxes2d in enumerate(boxes2d_list):
            each_boxes2d = torch.tensor(each_boxes2d)
            boxes2d[i, :each_boxes2d.shape[0], :] = each_boxes2d
            vis_mask[i, :each_boxes2d.shape[0]] = 1
        
        prev_boxes2d = torch.zeros((len(prev_boxes2d_list), max_obj_num, 4), dtype=self.data_type)
        prev_vis_mask = torch.zeros((len(prev_boxes2d_list), max_obj_num), dtype=torch.long)
        for i, each_boxes2d in enumerate(prev_boxes2d_list):
            each_boxes2d = torch.tensor(each_boxes2d)
            prev_boxes2d[i, :each_boxes2d.shape[0], :] = each_boxes2d
            prev_vis_mask[i, :each_boxes2d.shape[0]] = 1
        
        # points & prev_points
        objects_pc = raw_batch[2]
        points = torch.zeros((len(boxes2d_list), max_obj_num, self.sample_points_num, self.dim), dtype=self.data_type)
        for i, pt in enumerate(objects_pc):
            points[i, :pt.shape[0], :, :] = torch.tensor(pt)
        
        prev_objects_pc = raw_batch[8]
        prev_points = torch.zeros((len(prev_boxes2d_list), max_obj_num, self.sample_points_num, self.dim), dtype=self.data_type)
        for i, pt in enumerate(prev_objects_pc):
            prev_points[i, :pt.shape[0], :, :] = torch.tensor(pt)

        # spatial & prev_spatial
        spatial_list = raw_batch[3]
        spatial = torch.zeros((len(boxes2d_list), max_obj_num, self.spatial_dim), dtype=self.data_type)
        for i, box in enumerate(spatial_list):
            spatial[i, :box.shape[0], :] = torch.tensor(box)
        
        prev_spatial_list = raw_batch[9]
        prev_spatial = torch.zeros((len(boxes2d_list), max_obj_num, self.spatial_dim), dtype=self.data_type)
        for i, box in enumerate(prev_spatial_list):
            prev_spatial[i, :box.shape[0], :] = torch.tensor(box)

        # token
        token_list = raw_batch[4]
        max_token_num = 0
        for each_token in token_list:
            max_token_num = max(max_token_num, len(each_token))

        token = torch.zeros((len(boxes2d_list), max_token_num), dtype=torch.long)
        for i, each_token in enumerate(token_list):
            token[i, :len(each_token)] = torch.tensor(each_token)

        mask = torch.zeros((len(boxes2d_list), max_token_num), dtype=torch.long)
        mask[token != 0] = 1

        segment_ids = torch.zeros_like(mask)

        # target
        target_list = raw_batch[5]
        target = torch.zeros((len(boxes2d_list), max_obj_num), dtype=self.data_type)
        for i, each_target in enumerate(target_list):
            target[i, :len(each_target)] = torch.tensor(each_target) 
        
        # rel_dist_mask
        rel_dist_mask_list = raw_batch[10]
        rel_dist_mask = torch.zeros((len(boxes2d_list), max_obj_num, max_obj_num), dtype=torch.bool)
        for i, each_dist_mask in enumerate(rel_dist_mask_list):
            rel_dist_mask[i, :each_dist_mask.shape[0], :each_dist_mask.shape[1]] = torch.tensor(each_dist_mask)
   
        output = dict(
            image=image, boxes2d=boxes2d, points=points, spatial=spatial, vis_mask=vis_mask,
            prev_image=prev_image, prev_boxes2d=prev_boxes2d, prev_points=prev_points, prev_spatial=prev_spatial, prev_vis_mask=prev_vis_mask,
            token=token, mask=mask, segment_ids=segment_ids, 
            rel_dist_mask=rel_dist_mask,
            target=target
        )      

        return output
    
    def __len__(self):
        return len(self.dataset)
    
    def evaluate(self, index_list):
        target_boxes = []
        pred_boxes = []
        idx = 0
        for max_index in tqdm(index_list):
            data = self.dataset[idx]
            group_id = data['group_id']
            scene_id = data['scene_id']
            point_cloud_info = data['point_cloud']
            image_info = data['image']
            language_info = data['language']
            point_cloud_name = point_cloud_info['point_cloud_name']
            boxes3d = np.load(f"data/pred_bboxes/{group_id}/{scene_id}/{point_cloud_name[:-4]}.npy")
            pred_box = boxes3d[max_index]
            target = point_cloud_info['bbox']
            
            pred_boxes.append(pred_box)
            target_boxes.append(target)
            idx += 1
        
        target_boxes = np.array(target_boxes)
        pred_boxes = np.array(pred_boxes)

        acc25, acc50, miou = cal_accuracy(pred_boxes, target_boxes)
        return acc25, acc50, miou

    def visualize(self, args, index_list):
        import matplotlib.pyplot as plt
        base_path = args.vis_path

        if not os.path.exists(base_path):
            os.makedirs(base_path)

        idx = 0
        for max_index in tqdm(index_list):
            data = self.dataset[idx]
            boxes3d = np.load(f"detection_results/scannet/{data['scene_id']}/pcd_{data['object_id']}_{data['image_id']}.npy")
            bias = np.array(data['bias'])
            boxes3d[:, :3] += bias

            pred_box = boxes3d[max_index]
            target = np.array(data['object_box'])
            target[:3] += bias

            axis_align_matrix_path = f"/remote-home/share/ScannetForScanrefer/scans/{data['scene_id']}/{data['scene_id']}.txt"
            axis_align_matrix = strefer_utils.load_axis_align_matrix(axis_align_matrix_path)
            cam_pose_filename   = f"/remote-home/share/ScannetForScanrefer/scans/{data['scene_id']}/pose/{data['image_id']}.txt"
            cam_pose = np.loadtxt(cam_pose_filename)
            color_intrinsic_path = f"/remote-home/share/ScannetForScanrefer/scans/{data['scene_id']}/intrinsic/intrinsic_color.txt"
            color_intrinsic = np.loadtxt(color_intrinsic_path)

            target_corners_2d, _ = strefer_utils.box3d_to_2d(target, axis_align_matrix, cam_pose, color_intrinsic)
            pred_corners_2d, _ = strefer_utils.box3d_to_2d(pred_box, axis_align_matrix, cam_pose, color_intrinsic)

            image_path = data['image_path']
            img = cv2.imread(image_path)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            img = strefer_utils.draw_projected_box3d(img, target_corners_2d, (255, 0, 0), thickness=2)
            img = strefer_utils.draw_projected_box3d(img, pred_corners_2d, (0, 255, 0), thickness=2)

            filepath = os.path.join(base_path, f"{idx}.jpg")
            # fig = plt.figure(figsize=())
            sentence = data['sentence']
            sentence = sentence.split()
            if len(sentence) > 8:
                sentence.insert(8, '\n')
            if len(sentence) > 16:
                sentence.insert(16, '\n')
            sentence = ' '.join(sentence)
            plt.imshow(img)
            plt.axis('off')
            plt.title(f"{sentence}")
            plt.savefig(filepath, bbox_inches='tight')

            plt.clf()
            plt.close()

            idx += 1
        return