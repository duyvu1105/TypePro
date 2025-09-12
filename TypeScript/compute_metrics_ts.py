import json
import pandas as pd
import sys
import os
from TSTypeComparator.TSTypeObject import TSTypeObject
from TSTypeComparator.TSTypeComparator import TSTypeComparator

def calculate_top_k_accuracy(predictions_list, references, k=5):

    if len(predictions_list) != len(references):
        raise ValueError("The number of predictions does not match the number of reference answers.")
    
    top_k_correct_exact = 0
    top_k_correct_base = 0
    result = {}
    for pred_candidates, ref in zip(predictions_list, references):


        for pred in pred_candidates[:k]:
            pred = pred[0]
            gt_type_obj = TSTypeObject.str2obj(ref.strip())
            pre_type_obj = TSTypeObject.str2obj(pred.strip())
            if TSTypeComparator.is_identical_set(gt_type_obj, pre_type_obj):

                top_k_correct_exact +=1
                break

        for pred in pred_candidates[:k]:
            pred = pred[0]
            gt_type_obj = TSTypeObject.str2obj(ref.strip())
            pre_type_obj = TSTypeObject.str2obj(pred.strip())

            if TSTypeComparator.is_set_included2(gt_type_obj, pre_type_obj):

                top_k_correct_base +=1
                break


    result['exact']=top_k_correct_exact / len(references)
    result['base']=top_k_correct_base / len(references)
    
    return result

def calculate_MRR(predictions_list, references, n=5):
    result = {}
    mrr_exact = 0.0
    mrr_base = 0.0
    for pred_candidates, ref in zip(predictions_list, references):
        try:
            for i, pred in enumerate(pred_candidates[:n]):
                gt_type_obj = TSTypeObject.str2obj(ref.strip())
                pre_type_obj = TSTypeObject.str2obj(pred[0].strip())
                if TSTypeComparator.is_identical_set(gt_type_obj, pre_type_obj):mrr_exact += 1/(i+1);break

            for i, pred in enumerate(pred_candidates[:n]):
                gt_type_obj = TSTypeObject.str2obj(ref.strip())
                pre_type_obj = TSTypeObject.str2obj(pred[0].strip())
                if TSTypeComparator.is_set_included2(gt_type_obj, pre_type_obj):mrr_base += 1/(i+1);break
        except ValueError:mrr_base += 0
    

    mrr_exact /= len(predictions_list)
    mrr_base /= len(predictions_list)
    result['exact'] = mrr_exact
    result['base'] = mrr_base
    return result


def main():
    prediction_dicts_fp = './res.json'
    prediction_dicts = json.load(open(prediction_dicts_fp,'r'))
    

    result_exact = []
    result_base = []
    predictions_list_dict = {'var':[],'arg':[],'ret':[],'ele':[],'usr':[],'all':[]}
    references_dict = {'var':[],'arg':[],'ret':[],'ele':[],'usr':[],'all':[]}
    for prediction_dict in prediction_dicts:
        if prediction_dict['scope'] == 'var':
            predictions_list_dict['var'].append(prediction_dict['prediction'])
            references_dict['var'].append(prediction_dict['gttype'])
        elif prediction_dict['scope'] == 'arg':
            predictions_list_dict['arg'].append(prediction_dict['prediction'])
            references_dict['arg'].append(prediction_dict['gttype'])
        elif prediction_dict['scope'] == 'ret':
            predictions_list_dict['ret'].append(prediction_dict['prediction'])
            references_dict['ret'].append(prediction_dict['gttype'])
        
        if prediction_dict["cat"] == "user-defined":
            predictions_list_dict['usr'].append(prediction_dict['prediction'])
            references_dict['usr'].append(prediction_dict['gttype'])
        else :
            predictions_list_dict['ele'].append(prediction_dict['prediction'])
            references_dict['ele'].append(prediction_dict['gttype'])
            
        predictions_list_dict['all'].append(prediction_dict['prediction'])
        references_dict['all'].append(prediction_dict['gttype'])

    
    top_k = [1,3,5]
    n=5
    for cat in ['var','arg','ret','ele','usr','all']:
        temp_exact={'cat':cat}
        temp_base={'cat':cat}
        predictions_list = predictions_list_dict[cat]
        references = references_dict[cat]
        for k in top_k:
            temp_exact[f'Acc-Top{k}']=calculate_top_k_accuracy(predictions_list, references, k)['exact']
            temp_base[f'Acc-Top{k}']=calculate_top_k_accuracy(predictions_list, references, k)['base']
        temp_exact[f'MRR@{n}']=calculate_MRR(predictions_list, references, n)['exact']
        temp_base[f'MRR@{n}']=calculate_MRR(predictions_list, references, n)['base']
        result_exact.append(temp_exact)
        result_base.append(temp_base)

    directory='./output'
    if not os.path.exists(directory):
        os.makedirs(directory)
    pd.DataFrame(result_exact).to_csv(os.path.join(directory, 'metrics_exact.csv'),index=False)
    pd.DataFrame(result_base).to_csv(os.path.join(directory, 'metrics_base.csv'),index=False)

if __name__ == '__main__':
    main()