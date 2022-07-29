# STRefer

# TODO LIST

1. 1. [x] 数据集重新划分（把没有前一帧的数据清洗掉）
   
2. 2. [ ] 用pointnet++的backbone重新进行单帧输入/多帧输入的实验。
   1. [x] 单帧输入三组实验（pos_emb, view-base, vel-base)
   2. [ ] 多帧输入三组实验 
3. 3. [ ] 增加3DJCG对比实验
4. 4. [ ] 增加velocity误差
5. 5. [ ] 网络描述细化（参数更详细）
6. 6. [ ] 表格命名修订（更细化、明显）
7. 7. [ ] 细化数据集标注规则流程

# Dataset
数据集划分后：总共71个不同场景，56个场景划为训练场景，15个为测试场景。最终4392条训练集数据，1066条测试数据，测试集中出现的词至少在训练集中出现两次。

# Experiments
## Detection
| P@0.25 | R@0.25 | P@0.5 | R@0.5 |
|:------:|:------:|:-----:|:-----:|
| 88.29 | 90.97| 77.45 | 79.81 |

## Grounding
### Resnet34 & Pointnet++
| Method | Acc@0.25 | Acc@0.5 | mIOU |
|:------:|:------:|:------:|:-----:|
| Ours pos-emb | 42.40 | 39.77 | 32.73 |    (35)
| Ours view-emb | 44.93 | 42.03 | 34.53 |   (25)
| Ours view-vel-emb | 43.34 | 40.43 | 33.04 |   (35)