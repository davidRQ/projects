from __future__ import division
import time
import torch 
import torch.nn as nn
from torch.autograd import Variable
import numpy as np
import cv2 
from util import *
import argparse
import os 
import os.path as osp
from darknet import Darknet
from preprocess import prep_image, inp_to_image
import pandas as pd
import random 
import pickle as pkl
import itertools

class test_net(nn.Module):
    def __init__(self, num_layers, input_size):
        super(test_net, self).__init__()
        self.num_layers= num_layers
        self.linear_1 = nn.Linear(input_size, 5)
        self.middle = nn.ModuleList([nn.Linear(5,5) for x in range(num_layers)])
        self.output = nn.Linear(5,2)
    
    def forward(self, x):
        x = x.view(-1)
        fwd = nn.Sequential(self.linear_1, *self.middle, self.output)
        return fwd(x)
        
def get_test_input(input_dim, CUDA):
    img = cv2.imread("dog-cycle-car.png")
    img = cv2.resize(img, (input_dim, input_dim)) 
    img_ =  img[:,:,::-1].transpose((2,0,1))
    img_ = img_[np.newaxis,:,:,:]/255.0
    img_ = torch.from_numpy(img_).float()
    img_ = Variable(img_)
    
    if CUDA:
        img_ = img_.cuda()
    # num_classes
    return img_



def arg_parse():
    """
    Parse arguements to the detect module
    
    """
    
    
    parser = argparse.ArgumentParser(description='YOLO v3 Detection Module')
   
    parser.add_argument("--images", dest = 'images', help = 
                        "Image / Directory containing images to perform detection upon",
                        default = "imgs", type = str)
    parser.add_argument("--det", dest = 'det', help = 
                        "Image / Directory to store detections to",
                        default = "det", type = str)
    parser.add_argument("--bs", dest = "bs", help = "Batch size", default = 1)
    parser.add_argument("--confidence", dest = "confidence", help = "Object Confidence to filter predictions", default = 0.5)
    parser.add_argument("--nms_thresh", dest = "nms_thresh", help = "NMS Threshhold", default = 0.4)
    parser.add_argument("--cfg", dest = 'cfgfile', help = 
                        "Config file",
                        default = "cfg/yolov3.cfg", type = str)
    parser.add_argument("--weights", dest = 'weightsfile', help = 
                        "weightsfile",
                        default = "yolov3.weights", type = str)
    parser.add_argument("--reso", dest = 'reso', help = 
                        "Input resolution of the network. Increase to increase accuracy. Decrease to increase speed",
                        default = "416", type = str)
    parser.add_argument("--scales", dest = "scales", help = "Scales to use for detection",
                        default = "1,2,3", type = str)
    
    return parser.parse_args()




def detection(im, args, imagenes_predichas, time_processing_images):
    scales = args.scales

    images = im
    batch_size = int(args.bs)
    confidence = float(args.confidence)
    nms_thesh = float(args.nms_thresh)
    start = 0

    CUDA = torch.cuda.is_available()

    num_classes = 80
    classes = load_classes('data/coco.names') 

    #Set up the neural network
    # print("Loading network.....")
    model = Darknet(args.cfgfile)
    model.load_weights(args.weightsfile)
    # print("Network successfully loaded")
    
    model.net_info["height"] = args.reso
    inp_dim = int(model.net_info["height"])
    assert inp_dim % 32 == 0 
    assert inp_dim > 32

    #If there's a GPU availible, put the model on GPU
    if CUDA:
        model.cuda()
    
    
    #Set the model in evaluation mode
    model.eval()
    
    read_dir = time.time()
    #Detection phase
    try:
        imlist = [osp.join(osp.realpath('.'), images, img) for img in os.listdir(images) if os.path.splitext(img)[1] == '.png' or os.path.splitext(img)[1] =='.jpeg' or os.path.splitext(img)[1] =='.jpg']
    except NotADirectoryError:
        imlist = []
        imlist.append(osp.join(osp.realpath('.'), images))
    except FileNotFoundError:
        print ("No file or directory with the name {}".format(images))
        exit()
        
    if not os.path.exists(args.det):
        os.makedirs(args.det)
        
    load_batch = time.time()
    
    batches = list(map(prep_image, imlist, [inp_dim for x in range(len(imlist))]))
    im_batches = [x[0] for x in batches]
    orig_ims = [x[1] for x in batches]
    im_dim_list = [x[2] for x in batches]
    im_dim_list = torch.FloatTensor(im_dim_list).repeat(1,2)
        
    if CUDA:
        im_dim_list = im_dim_list.cuda()
    
    leftover = 0
    
    if (len(im_dim_list) % batch_size):
        leftover = 1
            
    if batch_size != 1:
        num_batches = len(imlist) // batch_size + leftover            
        im_batches = [torch.cat((im_batches[i*batch_size : min((i +  1)*batch_size,
                            len(im_batches))]))  for i in range(num_batches)]        

    i = 0    

    write = False
    model(get_test_input(inp_dim, CUDA), CUDA)
    
    start_det_loop = time.time()
    
    objs = {}
    
    for batch in im_batches:
        #load the image 
        start = time.time()
        if CUDA:
            batch = batch.cuda()
        with torch.no_grad():
            prediction = model(Variable(batch), CUDA)
        
        prediction = write_results(prediction, confidence, num_classes, nms = True, nms_conf = nms_thesh)

        if type(prediction) == int:
            i += 1
            continue
        end = time.time()
        prediction[:,0] += i*batch_size
          
        if not write:
            output = prediction
            write = 1
        else:
            output = torch.cat((output,prediction))

        for im_num, image in enumerate(imlist[i*batch_size: min((i +  1)*batch_size, len(imlist))]):
            im_id = i*batch_size + im_num
            objs = [classes[int(x[-1])] for x in output if int(x[0]) == im_id]
            scoress = [float(x[-2]) for x in output if int(x[0]) == im_id]

            imagenes_predichas[name] = [objs]
            imagenes_predichas[name].append(scoress)

            print("{0:20s} predicted in {1:6.3f} seconds".format(image.split("/")[-1], (end - start)/batch_size))
            print("{0:20s} {1:s}".format("Objects Detected:", " ".join(objs)))
            time_processing_images.append((end - start)/batch_size)
            print("----------------------------------------------------------")
        i += 1
        
        if CUDA:
            torch.cuda.synchronize()
    
    try:
        output
    except NameError:
        print("No detections were made")
        exit()
        
    im_dim_list = torch.index_select(im_dim_list, 0, output[:,0].long())
    
    scaling_factor = torch.min(inp_dim/im_dim_list,1)[0].view(-1,1)
    
    output[:,[1,3]] -= (inp_dim - scaling_factor*im_dim_list[:,0].view(-1,1))/2
    output[:,[2,4]] -= (inp_dim - scaling_factor*im_dim_list[:,1].view(-1,1))/2
    
    output[:,1:5] /= scaling_factor
    
    for i in range(output.shape[0]):
        output[i, [1,3]] = torch.clamp(output[i, [1,3]], 0.0, im_dim_list[i,0])
        output[i, [2,4]] = torch.clamp(output[i, [2,4]], 0.0, im_dim_list[i,1])
        
        
    output_recast = time.time()
    
    class_load = time.time()

    colors = pkl.load(open("pallete", "rb"))
    
    draw = time.time()


    def write(x, batches, results):
        c1 = tuple(x[1:3].int())
        c2 = tuple(x[3:5].int())
        img = results[int(x[0])]
        cls = int(x[-1])
        label = "{0}".format(classes[cls])
        color = random.choice(colors)
        cv2.rectangle(img, c1, c2,color, 1)
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 1 , 1)[0]
        c2 = c1[0] + t_size[0] + 3, c1[1] + t_size[1] + 4
        cv2.rectangle(img, c1, c2,color, -1)
        cv2.putText(img, label, (c1[0], c1[1] + t_size[1] + 4), cv2.FONT_HERSHEY_PLAIN, 1, [225,255,255], 1)
        return img
    
            
    list(map(lambda x: write(x, im_batches, orig_ims), output))
      
    det_names = pd.Series(imlist).apply(lambda x: "{}/det_{}".format(args.det,x.split("/")[-1]))
    
    
    end = time.time()
    
    # print()
    # print("SUMMARY")
    # print("----------------------------------------------------------")
    # print("{:25s}: {}".format("Task", "Time Taken (in seconds)"))
    # print()
    # print("{:25s}: {:2.3f}".format("Reading addresses", load_batch - read_dir))
    # print("{:25s}: {:2.3f}".format("Loading batch", start_det_loop - load_batch))
    # print("{:25s}: {:2.3f}".format("Detection (" + str(len(imlist)) +  " images)", output_recast - start_det_loop))
    # print("{:25s}: {:2.3f}".format("Output Processing", class_load - output_recast))
    # print("{:25s}: {:2.3f}".format("Drawing Boxes", end - draw))
    # print("{:25s}: {:2.3f}".format("Average time_per_img", (end - load_batch)/len(imlist)))
    # print("----------------------------------------------------------")
    
    torch.cuda.empty_cache()

if __name__ ==  '__main__':
    args = arg_parse()
    path = args.images

    imagenes = {}
    totales = {}

    f = open(path + "/labels.txt", "r")
    while(True):
        linea = f.readline()
        if not linea:
            break
        linea = np.array(linea.split())
        imagenes[ linea[0] ] = linea[1:]
        linea = linea[1:]

    f.close()

    imagenes_predichas = {}
    time_processing_images = []

    for name in imagenes:
        detection(path + "/" + name + ".jfif", args, imagenes_predichas, time_processing_images)
    
        # plt.figure(figsize=(10, 5))
        # plt.imshow(result_image)

    print(imagenes_predichas)
    print(time_processing_images)


    # imagenes = {}
    # totales = {}
    P = {}
    R = {}
    for k in imagenes_predichas:
        FP = 0
        TP = 0

        FN = 0

        # [1, 18, 1, 1, 1, 19, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1], [0.99957
        for i in range(len(imagenes_predichas[k][0])):
            if imagenes_predichas[k][1][i] < 0.75:
                if imagenes_predichas[k][1][i] > 0.6:
                    FP += 1
                else:
                    FN += 1
                imagenes_predichas[k][0][i] = -1

        # [1, 18, 1, 1, 1, 19]
        temp = []
        for x in imagenes_predichas[k][0]:
            if x != -1:
                temp.append(x)
        
        for i in imagenes[k]:
            veri = False
            for t in range(len(temp)):
                if i == temp[t]:
                    TP += 1
                    temp.pop(t)
                    veri = True
                    break
            if veri == False:
                FP += 1
        FP += len(temp)
        P[k] = float(TP) / (float(FP) + float(TP))
        R[k] = float(TP) / (float(TP) + float(FN))

    AP = 0
    for k in P:
        AP += P[k]
    AP /= len(P)

    AR = 0
    for k in R:
        AR += R[k]
    AR /= len(R)


    average_time_images = 0
    for k in time_processing_images:
        average_time_images += k
    average_time_images /= len(time_processing_images)

    print("\nTiempo por imagen en segundos :")
    print(time_processing_images)

    print("\nTiempo promedio de las imagenes en segundos:")
    print(average_time_images)

    print("\nPrecision de cada imagen:")
    print(P)

    print("\nAP 0.75 de cada imagen:")
    print(AP)

    print("\nRecall de cada imagen:")
    print(R)

    print("\nAR 0.75 de cada imagen:")
    print(AR)
