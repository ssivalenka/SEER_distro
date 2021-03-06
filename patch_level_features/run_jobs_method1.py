from shapely.geometry import LineString
from shapely.geometry.polygon import LinearRing
from shapely.geometry import Polygon
from shapely.geometry import MultiPolygon
from shapely.affinity import affine_transform
from shapely import ops
from shapely.validation import explain_validity   
from shapely.ops import polygonize
from shapely.ops import polygonize_full 
from skimage import color
from skimage import io
from skimage.color import separate_stains,hed_from_rgb
from skimage import data
from pymongo import MongoClient
from bson import json_util 
from bson.objectid import ObjectId
from matplotlib.path import Path
from PIL import Image
import openslide
import numpy as np
import time
import pprint
import json 
import collections
import csv
import sys
import os
import shutil
import subprocess
import pipes
import shlex
import math
import datetime
import random
import concurrent.futures 
import logging
from datetime import datetime

    
if __name__ == '__main__':
  if len(sys.argv)<2:
    print "usage:python run_jobs.py case_id user";
    exit(); 
    
  LOG_FILENAME = 'readme.log'  
  logging.basicConfig(filename=LOG_FILENAME,level=logging.DEBUG) 
  
  csv.field_size_limit(sys.maxsize);  
  max_workers=16;    
  
  case_id= sys.argv[1];
  user= sys.argv[2] ;
  
  image_list=[];  
  tmp_array=[[],[]];
  tmp_array[0]=case_id;   
  tmp_array[1]=user;
  image_list.append(tmp_array);   
  print image_list;  
   
  remote_image_folder="nfs001:/data/shared/tcga_analysis/seer_data/images";  
  my_home="/data1/bwang"    
  local_image_folder = os.path.join(my_home, 'img'); 
  if not os.path.exists(local_image_folder):
    print '%s folder do not exist, then create it.' % local_image_folder;
    os.makedirs(local_image_folder); 
        
  print " --- read config.json file ---" ;
  config_json_file_name = "config_cluster.json";  
  config_json_file = os.path.join(my_home, config_json_file_name);
  with open(config_json_file) as json_data:
    d = json.load(json_data);     
    patch_size =  d['patch_size'];   
    db_host = d['db_host'];
    db_port = d['db_port'];
    db_name1 = d['db_name1']; 
    db_name2 = d['db_name2'];
    print patch_size,db_host,db_port,db_name1,db_name2;
     
  client = MongoClient('mongodb://'+db_host+':'+db_port+'/');     
  db = client[db_name1];    
  images =db.images; 
  metadata=db.metadata;
  objects = db.objects;     
  
  db2 = client[db_name2];    
  images2 =db2.images; 
  metadata2=db2.metadata;
  objects2 = db2.objects;  
   
  collection_saved= db2.patch_level_features_batch_2;  
  
  image_width=0;
  image_height=0;    
  tolerance=1.0;
  patch_x_num=0; 
  patch_y_num=0;
  
  x, y = np.meshgrid(np.arange(patch_size), np.arange(patch_size)) # make a canvas with coordinates
  x, y = x.flatten(), y.flatten();
  points = np.vstack((x,y)).T ;
  
  #######################################
  def findImagePath(case_id):
    image_path="";  
    input_file="image_path.txt"
    image_path_file = os.path.join(my_home, input_file); 
    with open(image_path_file, 'r') as my_file:
      reader = csv.reader(my_file,delimiter=',')
      my_list = list(reader);
      for each_row in my_list:      
        file_path=each_row[0];#path
        if file_path.find(case_id) <> -1:#find it!
          image_path = each_row[0]; 
          image_path = image_path.replace('./','');       
          break
    return  image_path;  
  ###############################################  
  
  #############################################
  def findTumor_NonTumorRegions(case_id,user):
    execution_id=user+"_Tumor_Region";
    execution_id2=user+"_Non_Tumor_Region";
    
    #handle only tumor region overlap
    humanMarkupList_tumor=[];
    tmp_tumor_markup_list=[];
    
    for humarkup in objects.find({"provenance.image.case_id":case_id,
                                  "provenance.analysis.execution_id":execution_id},
                                 {"geometry":1,"_id":1}): 
      humarkup_polygon_tmp1=humarkup["geometry"]["coordinates"][0];
      mongo_record_id=humarkup["_id"];
      tmp_polygon=[tuple(i1) for i1 in humarkup_polygon_tmp1];
      tmp_polygon1 = Polygon(tmp_polygon);
      humarkup_polygon1 = tmp_polygon1.buffer(0);
      humarkup_polygon_bound1= humarkup_polygon1.bounds; 
           
      geom_type=tmp_polygon1.geom_type;
      validity=explain_validity(tmp_polygon1);
      if (geom_type=="Polygon") and (validity=="Valid Geometry"):
        goodMarkup=True;
      else:
        goodMarkup=False; 
      
      if not goodMarkup:        
        logging.debug(case_id);
        logging.debug(execution_id);
        logging.debug('This markup is NOT valid Geometry.');
        logging.debug(mongo_record_id);
        logging.debug(geom_type);
        logging.debug(validity);
        logging.debug(datetime.now());
        logging.debug('===============================================');
        #continue;           
      tmp_tumor_markup_list.append(humarkup);    
              
    index_intersected=[];                                
    for index1 in range(0, len(tmp_tumor_markup_list)):  
      if index1 in index_intersected :#skip polygon,which is been merged to another one
        continue;
      tmp_tumor_markup1=tmp_tumor_markup_list[index1];                               
      humarkup_polygon_tmp1=tmp_tumor_markup1["geometry"]["coordinates"][0];             
      tmp_polygon=[tuple(i1) for i1 in humarkup_polygon_tmp1];
      tmp_polygon1 = Polygon(tmp_polygon);    
      humarkup_polygon1 = tmp_polygon1.buffer(0);      
      humarkup_polygon_bound1= humarkup_polygon1.bounds;      
      is_within=False;
      is_intersect=False;
      for index2 in range(0, len(tmp_tumor_markup_list)):  
        tmp_tumor_markup2=tmp_tumor_markup_list[index2];                               
        humarkup_polygon_tmp2=tmp_tumor_markup2["geometry"]["coordinates"][0];             
        tmp_polygon2=[tuple(i2) for i2 in humarkup_polygon_tmp2];
        tmp_polygon22 = Polygon(tmp_polygon2);        
        humarkup_polygon2 = tmp_polygon22.buffer(0); 
        if (index1 <> index2):
          if (humarkup_polygon1.within(humarkup_polygon2)):    
            is_within=True;            
            break;              
          if (humarkup_polygon1.intersects(humarkup_polygon2)):
            humarkup_polygon1=humarkup_polygon1.union(humarkup_polygon2); 
            is_intersect=True;
            index_intersected.append(index2);                
      if(not is_within and not is_intersect):
        humanMarkupList_tumor.append(humarkup_polygon1);          
      if(is_within):
        continue;         
      if(is_intersect):          
        humanMarkupList_tumor.append(humarkup_polygon1);            
        
    #handle only non tumor region overlap
    humanMarkupList_non_tumor=[];
    tmp_non_tumor_markup_list=[];
    for humarkup in objects.find({"provenance.image.case_id":case_id,
                                  "provenance.analysis.execution_id":execution_id2},
                                 {"geometry":1,"_id":0}):
      tmp_non_tumor_markup_list.append(humarkup);     
        
    index_intersected=[];                                
    for index1 in range(0, len(tmp_non_tumor_markup_list)):  
      if index1 in index_intersected :#skip polygon,which is been merged to another one
        continue;
      tmp_tumor_markup1=tmp_non_tumor_markup_list[index1];                               
      humarkup_polygon_tmp1=tmp_tumor_markup1["geometry"]["coordinates"][0];             
      tmp_polygon=[tuple(i1) for i1 in humarkup_polygon_tmp1];
      tmp_polygon1 = Polygon(tmp_polygon);      
      humarkup_polygon1 = tmp_polygon1.convex_hull;
      humarkup_polygon1 = humarkup_polygon1.buffer(0);
      humarkup_polygon_bound1= humarkup_polygon1.bounds;
      is_within=False;
      is_intersect=False;
      for index2 in range(0, len(tmp_non_tumor_markup_list)):  
        tmp_tumor_markup2=tmp_non_tumor_markup_list[index2];                               
        humarkup_polygon_tmp2=tmp_tumor_markup2["geometry"]["coordinates"][0];             
        tmp_polygon2=[tuple(i2) for i2 in humarkup_polygon_tmp2];
        tmp_polygon22 = Polygon(tmp_polygon2);
        humarkup_polygon2=tmp_polygon22.convex_hull;
        humarkup_polygon2 = humarkup_polygon2.buffer(0);
        if (index1 <> index2):
          if (humarkup_polygon1.within(humarkup_polygon2)):    
            is_within=True;            
            break;              
          if (humarkup_polygon1.intersects(humarkup_polygon2)):
            humarkup_polygon1=humarkup_polygon1.union(humarkup_polygon2); 
            is_intersect=True;
            index_intersected.append(index2);                
      if(not is_within and not is_intersect):
        humanMarkupList_non_tumor.append(humarkup_polygon1);          
      if(is_within):
        continue;         
      if(is_intersect):          
        humanMarkupList_non_tumor.append(humarkup_polygon1);
        
    #handle tumor and non tumor region cross overlap
    for index1,tumor_region in enumerate(humanMarkupList_tumor):
      for index2,non_tumor_region in enumerate(humanMarkupList_non_tumor):
        if (tumor_region.within(non_tumor_region)): 
          ext_polygon_intersect_points =list(zip(*non_tumor_region.exterior.coords.xy));   
          int_polygon_intersect_points =list(zip(*tumor_region.exterior.coords.xy)); 
          newPoly = Polygon(ext_polygon_intersect_points,[int_polygon_intersect_points]);
          humanMarkupList_non_tumor[index2]=newPoly;#add a hole to this polygon
        elif (non_tumor_region.within(tumor_region)): 
          ext_polygon_intersect_points =list(zip(*tumor_region.exterior.coords.xy));   
          int_polygon_intersect_points =list(zip(*non_tumor_region.exterior.coords.xy)); 
          newPoly = Polygon(ext_polygon_intersect_points,[int_polygon_intersect_points]);
          humanMarkupList_tumor[index1]=newPoly;#add a hole to this polygon   
    
    return  humanMarkupList_tumor,humanMarkupList_non_tumor;     
  ################################################
  
  ###############################################
  def getCompositeDatasetExecutionID(case_id):
    execution_id="";
    for record in metadata2.find({"image.case_id":case_id,                 
				                          "provenance.analysis_execution_id":{'$regex' : 'composite_dataset', '$options' : 'i'}}).limit(1): 
      execution_id=record["provenance"]["analysis_execution_id"];
      break;
    return execution_id;    
  #################################################  
  
  ##################################
  def getMatrixValue(poly_in,patch_min_x_pixel,patch_min_y_pixel):          
    tmp_polygon =[];            
    for ii in range (0,len(poly_in)):   
      x0=poly_in[ii][0];
      y0=poly_in[ii][1];                 
      x01=(x0*image_width)- patch_min_x_pixel;
      y01=(y0*image_height)- patch_min_y_pixel;
      x01=int(round(x01)); 
      y01=int(round(y01));                
      point=[x01,y01];
      tmp_polygon.append(point);           
    if (len(tmp_polygon) >0):   
      path = Path(tmp_polygon)            
      grid = path.contains_points(points);
      return True,grid;
    else:
      return False, "";          
  ##################################################    
  
  #########################################################
  def saveFeatures2Mongo(case_id,image_width,image_height,user,patch_width_index,patch_height_index,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,grayscale_segment_mean,grayscale_segment_std,Hematoxylin_segment_mean,Hematoxylin_segment_std,grayscale_patch_10th_percentile,grayscale_patch_25th_percentile,grayscale_patch_50th_percentile,grayscale_patch_75th_percentile,grayscale_patch_90th_percentile,Hematoxylin_patch_10th_percentile,Hematoxylin_patch_25th_percentile,Hematoxylin_patch_50th_percentile,Hematoxylin_patch_75th_percentile,Hematoxylin_patch_90th_percentile,segment_10th_percentile_grayscale_intensity,segment_25th_percentile_grayscale_intensity,segment_50th_percentile_grayscale_intensity,segment_75th_percentile_grayscale_intensity,segment_90th_percentile_grayscale_intensity,segment_10th_percentile_hematoxylin_intensity,segment_25th_percentile_hematoxylin_intensity,segment_50th_percentile_hematoxylin_intensity,segment_75th_percentile_hematoxylin_intensity,segment_90th_percentile_hematoxylin_intensity):
    patch_feature_data = collections.OrderedDict();
    patch_feature_data['case_id'] = case_id;
    patch_feature_data['image_width'] = image_width;
    patch_feature_data['image_height'] = image_height;    
    patch_feature_data['user'] = user;
    patch_feature_data['patch_width_index'] = patch_width_index;
    patch_feature_data['patch_height_index'] = patch_height_index;
    patch_feature_data['patch_min_x_pixel'] =patch_min_x_pixel;
    patch_feature_data['patch_min_y_pixel'] = patch_min_y_pixel;
    patch_feature_data['patch_size'] = patch_size;
    patch_feature_data['patch_polygon_area'] = patch_polygon_area;    
    patch_feature_data['tumorFlag'] = tumorFlag;  
    patch_feature_data['nucleus_area'] = nucleus_area;  
    patch_feature_data['percent_nuclear_material'] = percent_nuclear_material;
    patch_feature_data['grayscale_patch_mean'] = grayscale_patch_mean;
    patch_feature_data['grayscale_patch_std'] = grayscale_patch_std;
    patch_feature_data['Hematoxylin_patch_mean'] = Hematoxylin_patch_mean;
    patch_feature_data['Hematoxylin_patch_std'] = Hematoxylin_patch_std;
    patch_feature_data['grayscale_segment_mean'] = grayscale_segment_mean;
    patch_feature_data['grayscale_segment_std'] = grayscale_segment_std;
    patch_feature_data['Hematoxylin_segment_mean'] = Hematoxylin_segment_mean;
    patch_feature_data['Hematoxylin_segment_std'] = Hematoxylin_segment_std;    
    patch_feature_data['grayscale_patch_10th_percentile'] = grayscale_patch_10th_percentile;  
    patch_feature_data['grayscale_patch_25th_percentile'] = grayscale_patch_25th_percentile;
    patch_feature_data['grayscale_patch_50th_percentile'] = grayscale_patch_50th_percentile;
    patch_feature_data['grayscale_patch_75th_percentile'] = grayscale_patch_75th_percentile;
    patch_feature_data['grayscale_patch_90th_percentile'] = grayscale_patch_90th_percentile;    
    patch_feature_data['Hematoxylin_patch_10th_percentile'] = Hematoxylin_patch_10th_percentile;  
    patch_feature_data['Hematoxylin_patch_25th_percentile'] = Hematoxylin_patch_25th_percentile;
    patch_feature_data['Hematoxylin_patch_50th_percentile'] = Hematoxylin_patch_50th_percentile;
    patch_feature_data['Hematoxylin_patch_75th_percentile'] = Hematoxylin_patch_75th_percentile;
    patch_feature_data['Hematoxylin_patch_90th_percentile'] = Hematoxylin_patch_90th_percentile;    
    patch_feature_data['segment_10th_percentile_grayscale_intensity'] = segment_10th_percentile_grayscale_intensity;  
    patch_feature_data['segment_25th_percentile_grayscale_intensity'] = segment_25th_percentile_grayscale_intensity;
    patch_feature_data['segment_50th_percentile_grayscale_intensity'] = segment_50th_percentile_grayscale_intensity;
    patch_feature_data['segment_75th_percentile_grayscale_intensity'] = segment_75th_percentile_grayscale_intensity;
    patch_feature_data['segment_90th_percentile_grayscale_intensity'] = segment_90th_percentile_grayscale_intensity;    
    patch_feature_data['segment_10th_percentile_hematoxylin_intensity'] = segment_10th_percentile_hematoxylin_intensity;  
    patch_feature_data['segment_25th_percentile_hematoxylin_intensity'] = segment_25th_percentile_hematoxylin_intensity;
    patch_feature_data['segment_50th_percentile_hematoxylin_intensity'] = segment_50th_percentile_hematoxylin_intensity;
    patch_feature_data['segment_75th_percentile_hematoxylin_intensity'] = segment_75th_percentile_hematoxylin_intensity;
    patch_feature_data['segment_90th_percentile_hematoxylin_intensity'] = segment_90th_percentile_hematoxylin_intensity;   
    patch_feature_data['datetime'] = datetime.now();               
    collection_saved.insert_one(patch_feature_data);         
  ######################################################################  
  
  #########################################################
  def saveFeatures2MongoDB(case_id,image_width,image_height,user,patch_width_index,patch_height_index,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,grayscale_segment_mean,grayscale_segment_std,Hematoxylin_segment_mean,Hematoxylin_segment_std,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std):
    patch_feature_data = collections.OrderedDict();
    patch_feature_data['case_id'] = case_id;
    patch_feature_data['image_width'] = image_width;
    patch_feature_data['image_height'] = image_height;    
    patch_feature_data['user'] = user;
    patch_feature_data['patch_width_index'] = patch_width_index;
    patch_feature_data['patch_height_index'] = patch_height_index;
    patch_feature_data['patch_min_x_pixel'] =patch_min_x_pixel;
    patch_feature_data['patch_min_y_pixel'] = patch_min_y_pixel;
    patch_feature_data['patch_size'] = patch_size;
    patch_feature_data['patch_polygon_area'] = patch_polygon_area;    
    patch_feature_data['tumorFlag'] = tumorFlag;  
    patch_feature_data['nucleus_area'] = nucleus_area;  
    patch_feature_data['percent_nuclear_material'] = percent_nuclear_material;
    patch_feature_data['grayscale_patch_mean'] = grayscale_patch_mean;
    patch_feature_data['grayscale_patch_std'] = grayscale_patch_std;
    patch_feature_data['Hematoxylin_patch_mean'] = Hematoxylin_patch_mean;
    patch_feature_data['Hematoxylin_patch_std'] = Hematoxylin_patch_std;
    patch_feature_data['grayscale_segment_mean'] = grayscale_segment_mean;
    patch_feature_data['grayscale_segment_std'] = grayscale_segment_std;
    patch_feature_data['Hematoxylin_segment_mean'] = Hematoxylin_segment_mean;
    patch_feature_data['Hematoxylin_segment_std'] = Hematoxylin_segment_std;       
    patch_feature_data['Flatness_segment_mean'] = Flatness_segment_mean;  
    patch_feature_data['Flatness_segment_std'] = Flatness_segment_std;
    patch_feature_data['Perimeter_segment_mean'] = Perimeter_segment_mean;
    patch_feature_data['Perimeter_segment_std'] = Perimeter_segment_std;
    patch_feature_data['Circularity_segment_mean'] = Circularity_segment_mean;    
    patch_feature_data['Circularity_segment_std'] = Circularity_segment_std;  
    patch_feature_data['r_GradientMean_segment_mean'] = r_GradientMean_segment_mean;
    patch_feature_data['r_GradientMean_segment_std'] = r_GradientMean_segment_std;
    patch_feature_data['b_GradientMean_segment_mean'] = b_GradientMean_segment_mean;
    patch_feature_data['b_GradientMean_segment_std'] = b_GradientMean_segment_std;    
    patch_feature_data['r_cytoIntensityMean_segment_mean'] = r_cytoIntensityMean_segment_mean;  
    patch_feature_data['r_cytoIntensityMean_segment_std'] = r_cytoIntensityMean_segment_std;
    patch_feature_data['b_cytoIntensityMean_segment_mean'] = b_cytoIntensityMean_segment_mean;
    patch_feature_data['b_cytoIntensityMean_segment_std'] = b_cytoIntensityMean_segment_std;   
    patch_feature_data['datetime'] = datetime.now();               
    collection_saved.insert_one(patch_feature_data);         
  ######################################################################   
  
  ######################################################################
  def process_one_patch(case_id,user,i,j,patch_polygon_area,image_width,image_height,patch_polygon_original,patchHumanMarkupRelation_tumor,patchHumanMarkupRelation_nontumor,patch_humanmarkup_intersect_polygon_tumor,patch_humanmarkup_intersect_polygon_nontumor,nuclues_polygon_list):    
    patch_min_x_pixel =int(patch_polygon_original[0][0]*image_width);
    patch_min_y_pixel =int(patch_polygon_original[0][1]*image_height);
    x10=patch_polygon_original[0][0];
    y10=patch_polygon_original[0][1];
    x20=patch_polygon_original[2][0];
    y20=patch_polygon_original[2][1];
    patch_width_unit=float(patch_size)/float(image_width); 
    patch_height_unit=float(patch_size)/float(image_height);
    
    try:
      patch_img= img.read_region((patch_min_x_pixel, patch_min_y_pixel), 0, (patch_size, patch_size));
    except openslide.OpenSlideError as detail:
      print 'Handling run-time error:', detail  
      exit();
    except Exception as e: 
      print(e);
      exit();
      
    tmp_poly=[tuple(i1) for i1 in patch_polygon_original];
    tmp_polygon = Polygon(tmp_poly);
    patch_polygon = tmp_polygon.buffer(0);
    #patch_polygon_bound= patch_polygon.bounds;
          
    grayscale_img = patch_img.convert('L');
    rgb_img = patch_img.convert('RGB');        
    grayscale_img_matrix=np.array(grayscale_img);  
    rgb_img_matrix=np.array(rgb_img);         
    grayscale_patch_mean=np.mean(grayscale_img_matrix);
    grayscale_patch_std=np.std(grayscale_img_matrix);    
    grayscale_patch_10th_percentile=np.percentile(grayscale_img_matrix,10);
    grayscale_patch_25th_percentile=np.percentile(grayscale_img_matrix,25);
    grayscale_patch_50th_percentile=np.percentile(grayscale_img_matrix,50);
    grayscale_patch_75th_percentile=np.percentile(grayscale_img_matrix,75);
    grayscale_patch_90th_percentile=np.percentile(grayscale_img_matrix,90);              
    hed_title_img = separate_stains(rgb_img_matrix, hed_from_rgb);     
    """           
    Hematoxylin_img_matrix = [[0 for x in range(patch_size)] for y in range(patch_size)] 
    for index1,row in enumerate(hed_title_img):
      for index2,pixel in enumerate(row):
        Hematoxylin_img_matrix[index1][index2]=pixel[0]; 
    """
    max1=np.max(hed_title_img);
    min1=np.min(hed_title_img);
    Hematoxylin_img_matrix=hed_title_img [:,:,0];
    Hematoxylin_img_matrix =((Hematoxylin_img_matrix -min1)*255/(max1-min1)).astype(np.uint8);    
    Hematoxylin_patch_mean=np.mean(Hematoxylin_img_matrix);
    Hematoxylin_patch_std=np.std(Hematoxylin_img_matrix);
    Hematoxylin_patch_10th_percentile=np.percentile(Hematoxylin_img_matrix,10);
    Hematoxylin_patch_25th_percentile=np.percentile(Hematoxylin_img_matrix,25);
    Hematoxylin_patch_50th_percentile=np.percentile(Hematoxylin_img_matrix,50);
    Hematoxylin_patch_75th_percentile=np.percentile(Hematoxylin_img_matrix,75);
    Hematoxylin_patch_90th_percentile=np.percentile(Hematoxylin_img_matrix,90);            
          
    nucleus_area=0.0;#tumor patch area
    nucleus_area2=0.0;#non_tumor patch area
    Flatness_list=[];
    Perimeter_list=[];
    Circularity_list=[];
    r_GradientMean_list=[];
    b_GradientMean_list=[];
    r_cytoIntensityMean_list=[];
    b_cytoIntensityMean_list=[];
    segment_img=[];
    segment_img_hematoxylin=[];         
    initial_grid=np.full((patch_size*patch_size), False); 
    findPixelWithinPolygon=False;     
    special_case1="";
    tumorFlag="";
    patchHumanMarkupRelation="";
    patch_humanmarkup_intersect_polygon = Polygon([(0, 0), (1, 1), (1, 0)]);
    
    if(patchHumanMarkupRelation_tumor=="intersect" and patchHumanMarkupRelation_nontumor=="intersect"):
      special_case1="both";
    elif (patchHumanMarkupRelation_tumor=="intersect"):
      special_case1="tumor";  
      tumorFlag="tumor";  
      patchHumanMarkupRelation="intersect";
      patch_humanmarkup_intersect_polygon=patch_humanmarkup_intersect_polygon_tumor;
    elif (patchHumanMarkupRelation_nontumor=="intersect"):
      special_case1="nontumor";
      tumorFlag="non_tumor";
      patchHumanMarkupRelation="intersect";
      patch_humanmarkup_intersect_polygon=patch_humanmarkup_intersect_polygon_nontumor;
    elif (patchHumanMarkupRelation_tumor=="within"):
      special_case1="tumor";  
      tumorFlag="tumor"; 
      patchHumanMarkupRelation="within";
      patch_humanmarkup_intersect_polygon=patch_humanmarkup_intersect_polygon_tumor;
    elif (patchHumanMarkupRelation_nontumor=="within"):
      special_case1="nontumor";
      tumorFlag="non_tumor";
      patchHumanMarkupRelation="within";
      patch_humanmarkup_intersect_polygon=patch_humanmarkup_intersect_polygon_nontumor;
      
         
    record_count =len(nuclues_polygon_list);
    if (record_count>0 and special_case1<>"both"):  
      print "---------------------";
      print case_id,user,i,j; 
      print "---------------------"                                                                   
      for nuclues_polygon in nuclues_polygon_list:                                            
        polygon=nuclues_polygon["geometry"]["coordinates"][0];
        features_array=nuclues_polygon["properties"]["scalar_features"][0]["nv"];                                 
        tmp_poly2=[tuple(i2) for i2 in polygon];
        computer_polygon2 = Polygon(tmp_poly2);
        computer_polygon = computer_polygon2.buffer(0);
        #computer_polygon_bound= computer_polygon.bounds;
        polygon_area= computer_polygon.area;                          
        special_case2=""; 
        
        #only calculate features within/intersect tumor or non tumor region 
        if (patchHumanMarkupRelation=="within"):
           special_case2="within";           
        elif (patchHumanMarkupRelation=="intersect"):              
          if(computer_polygon.within(patch_humanmarkup_intersect_polygon)):                
            special_case2="within";
          elif(computer_polygon.intersects(patch_humanmarkup_intersect_polygon)):               
            special_case2="intersects";
          else:                
            special_case2="disjoin";   
                                    
          if (special_case2=="disjoin"):
            continue;#skip this one and move to another computer polygon              
                       
        if (special_case2=="within" and computer_polygon.within(patch_polygon)):#within/within            
          nucleus_area=nucleus_area+polygon_area;     
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value); 
          has_value,one_polygon_mask=getMatrixValue(polygon,patch_min_x_pixel,patch_min_y_pixel); 
          if(has_value):
            initial_grid = initial_grid | one_polygon_mask; 
            findPixelWithinPolygon=True;                                        
        elif (special_case2=="within" and computer_polygon.intersects(patch_polygon)):#within/intersects 
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                            
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                    
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask; 
              findPixelWithinPolygon=True;             
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                    
        elif (special_case2=="intersects" and computer_polygon.within(patch_polygon)):#intersects/within
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue; 
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                          
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                               
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);   
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':                
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                              
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;   
              findPixelWithinPolygon=True;              
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                   
        elif (special_case2=="intersects" and computer_polygon.intersects(patch_polygon)):#intersects/intersects
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          polygon_intersect=polygon_intersect.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue;              
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                           
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                   
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                    
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                   
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;  
              findPixelWithinPolygon=True;               
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j);  
            print polygon_intersect;
    
    if(special_case1<>"both"):        
      if(findPixelWithinPolygon):          
        mask = initial_grid.reshape(patch_size,patch_size);             
        for index1,row in enumerate(mask):
          for index2,pixel in enumerate(row):
            if (pixel):#this pixel is inside of segmented unclei polygon                     
              segment_img.append(grayscale_img_matrix[index1][index2]);
              segment_img_hematoxylin.append(Hematoxylin_img_matrix[index1][index2]);     
               
      percent_nuclear_material =float((nucleus_area/patch_polygon_area)*100);   
          
      if (len(segment_img)>0):          
        segment_mean_grayscale_intensity= np.mean(segment_img);
        segment_std_grayscale_intensity= np.std(segment_img); 
        segment_10th_percentile_grayscale_intensity=np.percentile(segment_img,10); 
        segment_25th_percentile_grayscale_intensity=np.percentile(segment_img,25);
        segment_50th_percentile_grayscale_intensity=np.percentile(segment_img,50);
        segment_75th_percentile_grayscale_intensity=np.percentile(segment_img,75);
        segment_90th_percentile_grayscale_intensity=np.percentile(segment_img,90);
        segment_mean_hematoxylin_intensity= np.mean(segment_img_hematoxylin);
        segment_std_hematoxylin_intensity= np.std(segment_img_hematoxylin); 
        segment_10th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,10); 
        segment_25th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,25);
        segment_50th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,50);
        segment_75th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,75);
        segment_90th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,90);                    
      else:
        segment_mean_grayscale_intensity="n/a";
        segment_std_grayscale_intensity="n/a";
        segment_mean_hematoxylin_intensity="n/a";
        segment_std_hematoxylin_intensity="n/a";   
        segment_10th_percentile_grayscale_intensity="n/a";
        segment_25th_percentile_grayscale_intensity="n/a";
        segment_50th_percentile_grayscale_intensity ="n/a"; 
        segment_75th_percentile_grayscale_intensity="n/a"; 
        segment_90th_percentile_grayscale_intensity ="n/a"; 
        segment_10th_percentile_hematoxylin_intensity="n/a"; 
        segment_25th_percentile_hematoxylin_intensity="n/a";
        segment_50th_percentile_hematoxylin_intensity="n/a";
        segment_75th_percentile_hematoxylin_intensity="n/a";
        segment_90th_percentile_hematoxylin_intensity="n/a";     
      
      if (len(Flatness_list)>0):
        Flatness_segment_mean= np.mean(Flatness_list);
        Flatness_segment_std= np.std(Flatness_list); 
      else:
        Flatness_segment_mean="n/a";
        Flatness_segment_std="n/a";
              
      if (len(Perimeter_list)>0):
        Perimeter_segment_mean= np.mean(Perimeter_list);
        Perimeter_segment_std= np.std(Perimeter_list);  
      else:
        Perimeter_segment_mean="n/a";
        Perimeter_segment_std="n/a";
            
      if (len(Circularity_list)>0):
        Circularity_segment_mean= np.mean(Circularity_list);
        Circularity_segment_std= np.std(Circularity_list);  
      else:
        Circularity_segment_mean="n/a";
        Circularity_segment_std="n/a";
              
      if (len(r_GradientMean_list)>0):
        r_GradientMean_segment_mean= np.mean(r_GradientMean_list);
        r_GradientMean_segment_std= np.std(r_GradientMean_list);
      else:
        r_GradientMean_segment_mean="n/a";  
        r_GradientMean_segment_std="n/a";
        
      if (len(b_GradientMean_list)>0):
        b_GradientMean_segment_mean= np.mean(b_GradientMean_list);
        b_GradientMean_segment_std= np.std(b_GradientMean_list);
      else:
        b_GradientMean_segment_mean="n/a";
        b_GradientMean_segment_std="n/a";
          
      if (len(r_cytoIntensityMean_list)>0):
        r_cytoIntensityMean_segment_mean= np.mean(r_cytoIntensityMean_list);
        r_cytoIntensityMean_segment_std= np.std(r_cytoIntensityMean_list);
      else:
        r_cytoIntensityMean_segment_mean="n/a";
        r_cytoIntensityMean_segment_std="n/a";
          
      if (len(b_cytoIntensityMean_list)>0):
        b_cytoIntensityMean_segment_mean= np.mean(b_cytoIntensityMean_list);
        b_cytoIntensityMean_segment_std= np.std(b_cytoIntensityMean_list);
      else:
        b_cytoIntensityMean_segment_mean="n/a";
        b_cytoIntensityMean_segment_std="n/a";
                
      #print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity;         
      #saveFeatures2Mongo(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,grayscale_patch_10th_percentile,grayscale_patch_25th_percentile,grayscale_patch_50th_percentile,grayscale_patch_75th_percentile,grayscale_patch_90th_percentile,Hematoxylin_patch_10th_percentile,Hematoxylin_patch_25th_percentile,Hematoxylin_patch_50th_percentile,Hematoxylin_patch_75th_percentile,Hematoxylin_patch_90th_percentile,segment_10th_percentile_grayscale_intensity,segment_25th_percentile_grayscale_intensity,segment_50th_percentile_grayscale_intensity,segment_75th_percentile_grayscale_intensity,segment_90th_percentile_grayscale_intensity,segment_10th_percentile_hematoxylin_intensity,segment_25th_percentile_hematoxylin_intensity,segment_50th_percentile_hematoxylin_intensity,segment_75th_percentile_hematoxylin_intensity,segment_90th_percentile_hematoxylin_intensity); 
      print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std;
      print "\n";      
      saveFeatures2MongoDB(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std);     
    
    #case of both
    patchHumanMarkupRelation=patchHumanMarkupRelation_tumor;
    patch_humanmarkup_intersect_polygon= patch_humanmarkup_intersect_polygon_tumor;
    tumorFlag="tumor";
    if (record_count>0 and special_case1=="both"):                                                                      
      for nuclues_polygon in nuclues_polygon_list:                                            
        polygon=nuclues_polygon["geometry"]["coordinates"][0]; 
        features_array=nuclues_polygon["properties"]["scalar_features"][0]["nv"];                   
        tmp_poly2=[tuple(i2) for i2 in polygon];
        computer_polygon2 = Polygon(tmp_poly2);
        computer_polygon = computer_polygon2.buffer(0);
        #computer_polygon_bound= computer_polygon.bounds;
        polygon_area= computer_polygon.area;                          
        special_case2="";       
        
        #only calculate features within/intersect tumor or non tumor region 
        if (patchHumanMarkupRelation=="within"):
           special_case2="within";           
        elif (patchHumanMarkupRelation=="intersect"):              
          if(computer_polygon.within(patch_humanmarkup_intersect_polygon)):                
            special_case2="within";
          elif(computer_polygon.intersects(patch_humanmarkup_intersect_polygon)):               
            special_case2="intersects";
          else:                
            special_case2="disjoin";   
                                    
          if (special_case2=="disjoin"):
            continue;#skip this one and move to another computer polygon              
                       
        if (special_case2=="within" and computer_polygon.within(patch_polygon)):#within/within 
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          nucleus_area=nucleus_area+polygon_area;                                         
          has_value,one_polygon_mask=getMatrixValue(polygon,patch_min_x_pixel,patch_min_y_pixel); 
          if(has_value):
            initial_grid = initial_grid | one_polygon_mask; 
            findPixelWithinPolygon=True;                                        
        elif (special_case2=="within" and computer_polygon.intersects(patch_polygon)):#within/intersects   
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                            
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                    
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask; 
              findPixelWithinPolygon=True;             
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                    
        elif (special_case2=="intersects" and computer_polygon.within(patch_polygon)):#intersects/within
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue; 
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                          
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                               
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);   
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':                
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                              
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;   
              findPixelWithinPolygon=True;              
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                   
        elif (special_case2=="intersects" and computer_polygon.intersects(patch_polygon)):#intersects/intersects
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          polygon_intersect=polygon_intersect.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue;              
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                           
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                   
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                    
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                   
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;  
              findPixelWithinPolygon=True;               
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j);  
            print polygon_intersect;
    
    if(special_case1=="both" and tumorFlag=="tumor"):        
      if(findPixelWithinPolygon):          
        mask = initial_grid.reshape(patch_size,patch_size);             
        for index1,row in enumerate(mask):
          for index2,pixel in enumerate(row):
            if (pixel):#this pixel is inside of segmented unclei polygon                     
              segment_img.append(grayscale_img_matrix[index1][index2]);
              segment_img_hematoxylin.append(Hematoxylin_img_matrix[index1][index2]);     
               
      percent_nuclear_material =float((nucleus_area/patch_polygon_area)*100); 
              
      if (len(segment_img)>0):          
        segment_mean_grayscale_intensity= np.mean(segment_img);
        segment_std_grayscale_intensity= np.std(segment_img); 
        segment_10th_percentile_grayscale_intensity=np.percentile(segment_img,10); 
        segment_25th_percentile_grayscale_intensity=np.percentile(segment_img,25);
        segment_50th_percentile_grayscale_intensity=np.percentile(segment_img,50);
        segment_75th_percentile_grayscale_intensity=np.percentile(segment_img,75);
        segment_90th_percentile_grayscale_intensity=np.percentile(segment_img,90);
        segment_mean_hematoxylin_intensity= np.mean(segment_img_hematoxylin);
        segment_std_hematoxylin_intensity= np.std(segment_img_hematoxylin); 
        segment_10th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,10); 
        segment_25th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,25);
        segment_50th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,50);
        segment_75th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,75);
        segment_90th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,90);                    
      else:
        segment_mean_grayscale_intensity="n/a";
        segment_std_grayscale_intensity="n/a";
        segment_mean_hematoxylin_intensity="n/a";
        segment_std_hematoxylin_intensity="n/a";   
        segment_10th_percentile_grayscale_intensity="n/a";
        segment_25th_percentile_grayscale_intensity="n/a";
        segment_50th_percentile_grayscale_intensity ="n/a"; 
        segment_75th_percentile_grayscale_intensity="n/a"; 
        segment_90th_percentile_grayscale_intensity ="n/a"; 
        segment_10th_percentile_hematoxylin_intensity="n/a"; 
        segment_25th_percentile_hematoxylin_intensity="n/a";
        segment_50th_percentile_hematoxylin_intensity="n/a";
        segment_75th_percentile_hematoxylin_intensity="n/a";
        segment_90th_percentile_hematoxylin_intensity="n/a";
      
      if (len(Flatness_list)>0):
        Flatness_segment_mean= np.mean(Flatness_list);
        Flatness_segment_std= np.std(Flatness_list); 
      else:
        Flatness_segment_mean="n/a";
        Flatness_segment_std="n/a";
              
      if (len(Perimeter_list)>0):
        Perimeter_segment_mean= np.mean(Perimeter_list);
        Perimeter_segment_std= np.std(Perimeter_list);  
      else:
        Perimeter_segment_mean="n/a";
        Perimeter_segment_std="n/a";
            
      if (len(Circularity_list)>0):
        Circularity_segment_mean= np.mean(Circularity_list);
        Circularity_segment_std= np.std(Circularity_list);  
      else:
        Circularity_segment_mean="n/a";
        Circularity_segment_std="n/a";
              
      if (len(r_GradientMean_list)>0):
        r_GradientMean_segment_mean= np.mean(r_GradientMean_list);
        r_GradientMean_segment_std= np.std(r_GradientMean_list);
      else:
        r_GradientMean_segment_mean="n/a";  
        r_GradientMean_segment_std="n/a";
        
      if (len(b_GradientMean_list)>0):
        b_GradientMean_segment_mean= np.mean(b_GradientMean_list);
        b_GradientMean_segment_std= np.std(b_GradientMean_list);
      else:
        b_GradientMean_segment_mean="n/a";
        b_GradientMean_segment_std="n/a";
          
      if (len(r_cytoIntensityMean_list)>0):
        r_cytoIntensityMean_segment_mean= np.mean(r_cytoIntensityMean_list);
        r_cytoIntensityMean_segment_std= np.std(r_cytoIntensityMean_list);
      else:
        r_cytoIntensityMean_segment_mean="n/a";
        r_cytoIntensityMean_segment_std="n/a";
          
      if (len(b_cytoIntensityMean_list)>0):
        b_cytoIntensityMean_segment_mean= np.mean(b_cytoIntensityMean_list);
        b_cytoIntensityMean_segment_std= np.std(b_cytoIntensityMean_list);
      else:
        b_cytoIntensityMean_segment_mean="n/a";
        b_cytoIntensityMean_segment_std="n/a";        
              
      #print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity;         
      #saveFeatures2Mongo(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,grayscale_patch_10th_percentile,grayscale_patch_25th_percentile,grayscale_patch_50th_percentile,grayscale_patch_75th_percentile,grayscale_patch_90th_percentile,Hematoxylin_patch_10th_percentile,Hematoxylin_patch_25th_percentile,Hematoxylin_patch_50th_percentile,Hematoxylin_patch_75th_percentile,Hematoxylin_patch_90th_percentile,segment_10th_percentile_grayscale_intensity,segment_25th_percentile_grayscale_intensity,segment_50th_percentile_grayscale_intensity,segment_75th_percentile_grayscale_intensity,segment_90th_percentile_grayscale_intensity,segment_10th_percentile_hematoxylin_intensity,segment_25th_percentile_hematoxylin_intensity,segment_50th_percentile_hematoxylin_intensity,segment_75th_percentile_hematoxylin_intensity,segment_90th_percentile_hematoxylin_intensity);  
      print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std;  
      print "\n";   
      saveFeatures2MongoDB(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std);     
    
    #case of both   
    patchHumanMarkupRelation=patchHumanMarkupRelation_nontumor;
    patch_humanmarkup_intersect_polygon= patch_humanmarkup_intersect_polygon_nontumor;
    tumorFlag="non_tumor";      
    if (record_count>0 and special_case1=="both"):                                                                      
      for nuclues_polygon in nuclues_polygon_list:                                            
        polygon=nuclues_polygon["geometry"]["coordinates"][0]; 
        features_array=nuclues_polygon["properties"]["scalar_features"][0]["nv"];                    
        tmp_poly2=[tuple(i2) for i2 in polygon];
        computer_polygon2 = Polygon(tmp_poly2);
        computer_polygon = computer_polygon2.buffer(0);
        #computer_polygon_bound= computer_polygon.bounds;
        polygon_area= computer_polygon.area;                          
        special_case2=""; 
               
        #only calculate features within/intersect tumor or non tumor region 
        if (patchHumanMarkupRelation=="within"):
           special_case2="within";           
        elif (patchHumanMarkupRelation=="intersect"):              
          if(computer_polygon.within(patch_humanmarkup_intersect_polygon)):                
            special_case2="within";
          elif(computer_polygon.intersects(patch_humanmarkup_intersect_polygon)):               
            special_case2="intersects";
          else:                
            special_case2="disjoin";   
                                    
          if (special_case2=="disjoin"):
            continue;#skip this one and move to another computer polygon              
                       
        if (special_case2=="within" and computer_polygon.within(patch_polygon)):#within/within   
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          nucleus_area=nucleus_area+polygon_area;                                         
          has_value,one_polygon_mask=getMatrixValue(polygon,patch_min_x_pixel,patch_min_y_pixel); 
          if(has_value):
            initial_grid = initial_grid | one_polygon_mask; 
            findPixelWithinPolygon=True;                                        
        elif (special_case2=="within" and computer_polygon.intersects(patch_polygon)):#within/intersects  
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                            
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                    
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask; 
              findPixelWithinPolygon=True;             
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                    
        elif (special_case2=="intersects" and computer_polygon.within(patch_polygon)):#intersects/within
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue; 
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                          
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                               
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);   
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                
          elif polygon_intersect.geom_type == 'Polygon':                
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                              
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;   
              findPixelWithinPolygon=True;              
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j); 
            print polygon_intersect;                   
        elif (special_case2=="intersects" and computer_polygon.intersects(patch_polygon)):#intersects/intersects
          for item in features_array:          
            feature_name=item['name'];
            feature_value=item['value'];                     
            if(feature_name=="Flatness"):
              Flatness_list.append(feature_value);
            if(feature_name=="Perimeter"):
              Perimeter_list.append(feature_value);
            if(feature_name=="Circularity"):
              Circularity_list.append(feature_value);
            if(feature_name=="r_GradientMean"):
              r_GradientMean_list.append(feature_value);
            if(feature_name=="b_GradientMean"):
              b_GradientMean_list.append(feature_value);
            if(feature_name=="r_cytoIntensityMean"):
              r_cytoIntensityMean_list.append(feature_value);
            if(feature_name=="b_cytoIntensityMean"):
              b_cytoIntensityMean_list.append(feature_value);
          starttime=time.time();
          polygon_intersect=computer_polygon.intersection(patch_polygon);
          if polygon_intersect.is_empty:
            continue;
          polygon_intersect=polygon_intersect.intersection(patch_humanmarkup_intersect_polygon); 
          if polygon_intersect.is_empty:
            continue;              
          tmp_area=polygon_intersect.area;
          nucleus_area=nucleus_area+tmp_area;                           
          if polygon_intersect.geom_type == 'MultiPolygon':                                 
            for p in polygon_intersect:
              polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                   
              has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
              if(has_value):
                initial_grid = initial_grid | one_polygon_mask; 
                findPixelWithinPolygon=True;                                                                    
          elif polygon_intersect.geom_type == 'Polygon':               
            polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                   
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);
            if(has_value):
              initial_grid = initial_grid | one_polygon_mask;  
              findPixelWithinPolygon=True;               
          else:               
            print "patch indexes %d , %d Shape is not a polygon!!!" %(i,j);  
            print polygon_intersect;
    
    if(special_case1=="both" and tumorFlag=="non_tumor"):        
      if(findPixelWithinPolygon):          
        mask = initial_grid.reshape(patch_size,patch_size);             
        for index1,row in enumerate(mask):
          for index2,pixel in enumerate(row):
            if (pixel):#this pixel is inside of segmented unclei polygon                     
              segment_img.append(grayscale_img_matrix[index1][index2]);
              segment_img_hematoxylin.append(Hematoxylin_img_matrix[index1][index2]);     
               
      percent_nuclear_material =float((nucleus_area/patch_polygon_area)*100);  
             
      if (len(segment_img)>0):          
        segment_mean_grayscale_intensity= np.mean(segment_img);
        segment_std_grayscale_intensity= np.std(segment_img); 
        segment_10th_percentile_grayscale_intensity=np.percentile(segment_img,10); 
        segment_25th_percentile_grayscale_intensity=np.percentile(segment_img,25);
        segment_50th_percentile_grayscale_intensity=np.percentile(segment_img,50);
        segment_75th_percentile_grayscale_intensity=np.percentile(segment_img,75);
        segment_90th_percentile_grayscale_intensity=np.percentile(segment_img,90);
        segment_mean_hematoxylin_intensity= np.mean(segment_img_hematoxylin);
        segment_std_hematoxylin_intensity= np.std(segment_img_hematoxylin); 
        segment_10th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,10); 
        segment_25th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,25);
        segment_50th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,50);
        segment_75th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,75);
        segment_90th_percentile_hematoxylin_intensity=np.percentile(segment_img_hematoxylin,90);                    
      else:
        segment_mean_grayscale_intensity="n/a";
        segment_std_grayscale_intensity="n/a";
        segment_mean_hematoxylin_intensity="n/a";
        segment_std_hematoxylin_intensity="n/a";   
        segment_10th_percentile_grayscale_intensity="n/a";
        segment_25th_percentile_grayscale_intensity="n/a";
        segment_50th_percentile_grayscale_intensity ="n/a"; 
        segment_75th_percentile_grayscale_intensity="n/a"; 
        segment_90th_percentile_grayscale_intensity ="n/a"; 
        segment_10th_percentile_hematoxylin_intensity="n/a"; 
        segment_25th_percentile_hematoxylin_intensity="n/a";
        segment_50th_percentile_hematoxylin_intensity="n/a";
        segment_75th_percentile_hematoxylin_intensity="n/a";
        segment_90th_percentile_hematoxylin_intensity="n/a";      
       
      if (len(Flatness_list)>0):
        Flatness_segment_mean= np.mean(Flatness_list);
        Flatness_segment_std= np.std(Flatness_list); 
      else:
        Flatness_segment_mean="n/a";
        Flatness_segment_std="n/a";
              
      if (len(Perimeter_list)>0):
        Perimeter_segment_mean= np.mean(Perimeter_list);
        Perimeter_segment_std= np.std(Perimeter_list);  
      else:
        Perimeter_segment_mean="n/a";
        Perimeter_segment_std="n/a";
            
      if (len(Circularity_list)>0):
        Circularity_segment_mean= np.mean(Circularity_list);
        Circularity_segment_std= np.std(Circularity_list);  
      else:
        Circularity_segment_mean="n/a";
        Circularity_segment_std="n/a";
              
      if (len(r_GradientMean_list)>0):
        r_GradientMean_segment_mean= np.mean(r_GradientMean_list);
        r_GradientMean_segment_std= np.std(r_GradientMean_list);
      else:
        r_GradientMean_segment_mean="n/a";  
        r_GradientMean_segment_std="n/a";
        
      if (len(b_GradientMean_list)>0):
        b_GradientMean_segment_mean= np.mean(b_GradientMean_list);
        b_GradientMean_segment_std= np.std(b_GradientMean_list);
      else:
        b_GradientMean_segment_mean="n/a";
        b_GradientMean_segment_std="n/a";
          
      if (len(r_cytoIntensityMean_list)>0):
        r_cytoIntensityMean_segment_mean= np.mean(r_cytoIntensityMean_list);
        r_cytoIntensityMean_segment_std= np.std(r_cytoIntensityMean_list);
      else:
        r_cytoIntensityMean_segment_mean="n/a";
        r_cytoIntensityMean_segment_std="n/a";
          
      if (len(b_cytoIntensityMean_list)>0):
        b_cytoIntensityMean_segment_mean= np.mean(b_cytoIntensityMean_list);
        b_cytoIntensityMean_segment_std= np.std(b_cytoIntensityMean_list);
      else:
        b_cytoIntensityMean_segment_mean="n/a";
        b_cytoIntensityMean_segment_std="n/a";        
              
      #print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity;         
      #saveFeatures2Mongo(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,grayscale_patch_10th_percentile,grayscale_patch_25th_percentile,grayscale_patch_50th_percentile,grayscale_patch_75th_percentile,grayscale_patch_90th_percentile,Hematoxylin_patch_10th_percentile,Hematoxylin_patch_25th_percentile,Hematoxylin_patch_50th_percentile,Hematoxylin_patch_75th_percentile,Hematoxylin_patch_90th_percentile,segment_10th_percentile_grayscale_intensity,segment_25th_percentile_grayscale_intensity,segment_50th_percentile_grayscale_intensity,segment_75th_percentile_grayscale_intensity,segment_90th_percentile_grayscale_intensity,segment_10th_percentile_hematoxylin_intensity,segment_25th_percentile_hematoxylin_intensity,segment_50th_percentile_hematoxylin_intensity,segment_75th_percentile_hematoxylin_intensity,segment_90th_percentile_hematoxylin_intensity);  
      print case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std; 
      print "\n"; 
      saveFeatures2MongoDB(case_id,image_width,image_height,user,i,j,patch_min_x_pixel,patch_min_y_pixel,patch_size,patch_polygon_area,tumorFlag,nucleus_area,percent_nuclear_material,grayscale_patch_mean,grayscale_patch_std,Hematoxylin_patch_mean,Hematoxylin_patch_std,segment_mean_grayscale_intensity,segment_std_grayscale_intensity,segment_mean_hematoxylin_intensity,segment_std_hematoxylin_intensity,Flatness_segment_mean,Flatness_segment_std,Perimeter_segment_mean,Perimeter_segment_std,Circularity_segment_mean,Circularity_segment_std,r_GradientMean_segment_mean,r_GradientMean_segment_std,b_GradientMean_segment_mean,b_GradientMean_segment_std,r_cytoIntensityMean_segment_mean,r_cytoIntensityMean_segment_std,b_cytoIntensityMean_segment_mean,b_cytoIntensityMean_segment_std);      
  #####################################################################
  
  ###############################################
  def validateNuclearArea(index_i,index_j,nuclues_polygon_list):    
    patch_min_x_pixel=index_i*patch_size;
    patch_min_y_pixel=index_j*patch_size;  
    patch_width_unit=float(patch_size)/float(image_width); 
    patch_height_unit=float(patch_size)/float(image_height);  
    x10=float(index_i*float(patch_size))/float(image_width);
    y10=float(index_j*float(patch_size))/float(image_height);
    x20=float((index_i+1)*float(patch_size))/float(image_width);
    y20=float((index_j+1)*float(patch_size))/float(image_height);          
    patch_polygon1=[[x10,y10],[x20,y10],[x20,y20],[x10,y20],[x10,y10]];
    tmp_poly=[tuple(i1) for i1 in patch_polygon1];
    tmp_polygon = Polygon(tmp_poly);
    patch_polygon = tmp_polygon.buffer(0);      
    patch_min_x_pixel =int(patch_polygon1[0][0]*image_width);
    patch_min_y_pixel =int(patch_polygon1[0][1]*image_height);
    initial_grid=np.full((patch_size*patch_size), False); 
    findPixelWithinPolygon=False;     
    pixel_count=0;
    for nuclues_polygon in nuclues_polygon_list:                                            
      polygon=nuclues_polygon["geometry"]["coordinates"][0];                                         
      tmp_poly2=[tuple(i2) for i2 in polygon];
      computer_polygon2 = Polygon(tmp_poly2);
      computer_polygon = computer_polygon2.buffer(0);        
      polygon_area= computer_polygon.area; 
                                   
      if (computer_polygon.within(patch_polygon)):#within            
        has_value,one_polygon_mask=getMatrixValue(polygon,patch_min_x_pixel,patch_min_y_pixel);         
        if(has_value):            
          mask = one_polygon_mask.reshape(patch_size,patch_size);             
          for index1,row in enumerate(mask):
            for index2,pixel in enumerate(row):
              if (pixel):#this pixel is inside of unclei polygon                     
                pixel_count+=1;                         
      elif (computer_polygon.intersects(patch_polygon)):#intersects            
        polygon_intersect=computer_polygon.intersection(patch_polygon);
        if polygon_intersect.is_empty:
          continue;                                      
        if polygon_intersect.geom_type == 'MultiPolygon':                                          
          for p in polygon_intersect:            
            polygon_intersect_points =list(zip(*p.exterior.coords.xy));                                    
            has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
            if(has_value):              
              mask = one_polygon_mask.reshape(patch_size,patch_size);             
              for index1,row in enumerate(mask):
                for index2,pixel in enumerate(row):
                  if (pixel):#this pixel is inside of unclei polygon                     
                    pixel_count+=1;                                                                                
        elif polygon_intersect.geom_type == 'Polygon':                         
          polygon_intersect_points =list(zip(*polygon_intersect.exterior.coords.xy));                                
          has_value,one_polygon_mask=getMatrixValue(polygon_intersect_points,patch_min_x_pixel,patch_min_y_pixel);  
          if(has_value):            
            mask = one_polygon_mask.reshape(patch_size,patch_size);             
            for index1,row in enumerate(mask):
              for index2,pixel in enumerate(row):
                if (pixel):#this pixel is inside of unclei polygon                     
                  pixel_count+=1;                  
       
    print " -- pixel_count --";
    print pixel_count;                    
    percentage_nuclear=float(pixel_count)/float(patch_size*patch_size)*100.0;    
    return percentage_nuclear;    
  ################################################# 
  
  print '--- process image_list  ---- ';   
  for item in image_list:  
    case_id=item[0];
    user=item[1];      
    execution_id=user+"_Tumor_Region";
    execution_id2=user+"_Non_Tumor_Region";
    print case_id,user,execution_id,execution_id2;   
    #download image svs file to local folder
    image_file_name=case_id+".svs";
    image_file = os.path.join(local_image_folder, image_file_name);         
    if not os.path.isfile(image_file):
      print "image svs file is not available, then download it to local folder.";
      img_path=findImagePath(case_id);
      full_image_file = os.path.join(remote_image_folder, img_path);      
      subprocess.call(['scp', full_image_file,local_image_folder]);   
       
    image_file = os.path.join(local_image_folder, image_file_name);
    print image_file;    
    try:
      img = openslide.OpenSlide(image_file);      
    except Exception as e: 
      print(e);
      continue; 
      
    image_width =img.dimensions[0];
    image_height =img.dimensions[1];    
    patch_x_num=math.ceil(image_width/patch_size) ;
    patch_y_num=math.ceil(image_height/patch_size) ;  
    patch_x_num =int(patch_x_num);
    patch_y_num =int(patch_y_num);    
    humanMarkupList_tumor,humanMarkupList_non_tumor=findTumor_NonTumorRegions(case_id,user); 
        
    if(len(humanMarkupList_tumor) ==0 and humanMarkupList_non_tumor==0):
      print "No tumor or non tumor regions has been marked in this image by user %s." % user;
      continue;  
    comp_execution_id=getCompositeDatasetExecutionID(case_id);  
    if(comp_execution_id==""):
      print "Composite dataset for this image is NOT available.";  
      continue;     
             
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:                  
      for i in range(0,patch_x_num):
        for j in  range (0,patch_y_num):                                 
          patchHumanMarkupRelation_tumor="disjoin";
          patchHumanMarkupRelation_nontumor="disjoin";  
          tumor_related_patch=False;
          non_tumor_related_patch=False;          
          patch_humanmarkup_intersect_polygon_tumor = Polygon([(0, 0), (1, 1), (1, 0)]);
          patch_humanmarkup_intersect_polygon_nontumor = Polygon([(0, 0), (1, 1), (1, 0)]);
          patch_min_x_pixel=i*patch_size;
          patch_min_y_pixel=j*patch_size;  
          patch_width_unit=float(patch_size)/float(image_width); 
          patch_height_unit=float(patch_size)/float(image_height);  
          x10=float(i*float(patch_size))/float(image_width);
          y10=float(j*float(patch_size))/float(image_height);
          x20=float((i+1)*float(patch_size))/float(image_width);
          y20=float((j+1)*float(patch_size))/float(image_height);          
          patch_polygon1=[[x10,y10],[x20,y10],[x20,y20],[x10,y20],[x10,y10]];
          tmp_poly=[tuple(i1) for i1 in patch_polygon1];
          tmp_polygon = Polygon(tmp_poly);
          patch_polygon = tmp_polygon.buffer(0);
          #patch_polygon_bound= patch_polygon.bounds;
          patch_polygon_area=patch_polygon.area;
          
          for humanMarkup in humanMarkupList_tumor:
            #print i,j,humanMarkup.bounds;             
            if (patch_polygon.within(humanMarkup)):
              #print "-- within --" ;
              patchHumanMarkupRelation_tumor="within";
              tumor_related_patch=True;
              break;
            elif (patch_polygon.intersects(humanMarkup)):
              #print "-- intersects --";  
              patchHumanMarkupRelation_tumor="intersect";  
              patch_humanmarkup_intersect_polygon_tumor=humanMarkup;
              tumor_related_patch=True;
              break;
            else: 
              #print "-- disjoin --"; 
              patchHumanMarkupRelation_tumor="disjoin";           
            
          for humanMarkup2 in humanMarkupList_non_tumor:
            #print i,j,humanMarkup2.bounds;            
            if (patch_polygon.within(humanMarkup2)):
              #print "-- within --" ;
              patchHumanMarkupRelation_nontumor="within";
              non_tumor_related_patch=True;
              break;
            elif (patch_polygon.intersects(humanMarkup2)):
              #print "-- intersects --";  
              patchHumanMarkupRelation_nontumor="intersect";  
              patch_humanmarkup_intersect_polygon_nontumor=humanMarkup2;
              non_tumor_related_patch=True;
              break;
            else: 
              #print "-- disjoin --"; 
              patchHumanMarkupRelation_nontumor="disjoin";          
                      
          #only calculate features within/intersect tumor/non tumor region           
          if(patchHumanMarkupRelation_tumor=="disjoin" and patchHumanMarkupRelation_nontumor=="disjoin"):                     
            continue;        
               
          nuclues_polygon_list=[];
          x1_new=float(x10-(patch_width_unit*tolerance));
          y1_new=float(y10-(patch_height_unit*tolerance));
          x2_new=float(x20+(patch_width_unit*tolerance));
          y2_new=float(y20+(patch_height_unit*tolerance));  
          #deal with out of boundry 
          if x1_new>1.0:
            x1_new=1.0;
          if x1_new<0.0:
            x1_new=0.0; 
          if x2_new>1.0:
            x2_new=1.0;            
          if x2_new<0.0:
            x2_new=0.0;            
          if y1_new>1.0:
            y1_new=1.0;
          if y1_new<0.0:
            y1_new=0.0; 
          if y2_new>1.0:
            y2_new=1.0;
          if y2_new<0.0:
            y2_new=0.0;                                                       
          for nuclues_polygon in objects2.find({"provenance.image.case_id":case_id,
                                                "provenance.analysis.execution_id":comp_execution_id,                                                                                                   
                                                "x" : { '$gte':x1_new, '$lte':x2_new},
                                                "y" : { '$gte':y1_new, '$lte':y2_new} },
                                                {"geometry":1,"properties":1,"_id":0}):
            nuclear_polygon=nuclues_polygon["geometry"]["coordinates"][0]; 
            #exclude those nuclear objects, which are out of patch boundry
            take_this_polygon=False;
            tmp_poly=[tuple(i2) for i2 in nuclear_polygon];
            computer_polygon_obj = Polygon(tmp_poly);
            computer_polygon_obj2 = computer_polygon_obj.buffer(0);
            if (computer_polygon_obj2.within(patch_polygon)):
              take_this_polygon=True;
            if (computer_polygon_obj2.intersects(patch_polygon)):
              take_this_polygon=True;
            if not take_this_polygon:
              continue; 
            #filter to eliminate invalid  nuclues_polygon  
            validity=explain_validity(computer_polygon_obj);            
            if (validity=="Valid Geometry"):                                                  
              nuclues_polygon_list.append(nuclues_polygon); 
            else:
              print "find a invalid nuclues_polygon";  
              print  "case_id,user,i,j,comp_execution_id,x1_new,x2_new,y1_new,y2_new";
              print  case_id,user,i,j,comp_execution_id,x1_new,x2_new,y1_new,y2_new;  
              
          #print "validateNuclearArea(i,j,nuclues_polygon_list)";
          #print i,j,validateNuclearArea(i,j,nuclues_polygon_list);                                                                 
          executor.submit(process_one_patch,case_id,user,i,j,patch_polygon_area,image_width,image_height,patch_polygon1,patchHumanMarkupRelation_tumor,patchHumanMarkupRelation_nontumor,patch_humanmarkup_intersect_polygon_tumor,patch_humanmarkup_intersect_polygon_nontumor,nuclues_polygon_list);                                                       
    img.close();            
  exit();  
 
