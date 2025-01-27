import pickle as pkl
import tensorflow as tf
import time, json
import datetime
import numpy as np
import argparse

from random import random

import sys,os

sys.path.append("..")

from model.esim.esim import ESIM
from model.biblosa.biblosa import BiBLOSA
from model.transformer.base_transformer import BaseTransformer
from model.transformer.universal_transformer import UniversalTransformer

from data import data_clean
from data import data_utils 
from data import get_batch_data
from data import namespace_utils

from utils import logger_utils
from collections import OrderedDict

data_clearner_api = data_clean.DataCleaner({})
cut_tool = data_utils.cut_tool_api()

def prepare_data(data_path, w2v_path, vocab_path, make_vocab=True):

    [corpus, 
    corpus_label,
    corpus_len] = data_utils.read_classify_data(data_path, 
                    "train", 
                    cut_tool, 
                    data_clearner_api,
                    "tab")

    print("======max corpus label======", max(corpus_label))

    if make_vocab:
        dic = data_utils.make_dic(corpus)
        data_utils.read_pretrained_embedding(w2v_path, dic, vocab_path, min_freq=3)

    if sys.version_info < (3, ):
        embedding_info = pkl.load(open(os.path.join(vocab_path), "rb"))
    else:
        embedding_info = pkl.load(open(os.path.join(vocab_path), "rb"), 
                                encoding="iso-8859-1")

    return [corpus, corpus_label, corpus_len, embedding_info]

def train(config):
    model_config_path = config["model_config_path"]
    FLAGS = namespace_utils.load_namespace(model_config_path)

    os.environ["CUDA_VISIBLE_DEVICES"] = config.get("gpu_id", "")
    train_path = config["train_path"]
    w2v_path = config["w2v_path"]
    vocab_path = config["vocab_path"]
    dev_path = config["dev_path"]

    model_dir = config["model_dir"]
    model_name = config["model"]

    if not os.path.exists(model_dir):
        os.mkdir(model_dir)

    if not os.path.exists(os.path.join(model_dir, model_name)):
        os.mkdir(os.path.join(model_dir, model_name))

    if not os.path.exists(os.path.join(model_dir, model_name, "logs")):
        os.mkdir(os.path.join(model_dir, model_name, "logs"))

    if not os.path.exists(os.path.join(model_dir, model_name, "models")):
        os.mkdir(os.path.join(model_dir, model_name, "models"))

    json.dump(FLAGS, open(os.path.join(model_dir, model_name, "logs", model_name+".json"), "w"))
    logger = logger_utils.get_logger(os.path.join(model_dir, model_name, "logs","log.info"))

    [train_corpus, 
    train_corpus_label, 
    train_corpus_len, 
    embedding_info] = prepare_data(train_path, 
                        w2v_path, vocab_path,
                        make_vocab=True)

    token2id = embedding_info["token2id"]
    id2token = embedding_info["id2token"]
    embedding_mat = embedding_info["embedding_matrix"]
    extral_symbol = embedding_info["extra_symbol"]

    FLAGS.token_emb_mat = embedding_mat
    FLAGS.char_emb_mat = 0
    FLAGS.vocab_size = embedding_mat.shape[0]
    FLAGS.char_vocab_size = 0
    FLAGS.emb_size = embedding_mat.shape[1]
    FLAGS.extra_symbol = extral_symbol

    if FLAGS.scope == "ESIM":
        model = ESIM()
    elif FLAGS.scope == "BiBLOSA":
        model = BiBLOSA()
    elif FLAGS.scope == "BaseTransformer":
        model = BaseTransformer()
    elif FLAGS.scope == "UniversalTransformer":
        model = UniversalTransformer()

    model.build_placeholder(FLAGS)
    model.build_op()
    model.init_step()

    best_train_accuracy, best_train_loss = 0, 100
    toleration = 1000
    toleration_cnt = 0
    for epoch in range(FLAGS.max_epochs):
        train_loss, train_accuracy = 0, 0
        train_data = get_batch_data.get_classify_batch(train_corpus, 
                    train_corpus_label, FLAGS.batch_size, 
                    token2id, is_training=True,
                    if_word_drop=FLAGS.with_word_drop, 
                    word_drop_rate=FLAGS.word_drop_rate)

        nan_data = []
        cnt = 0
        for index, corpus in enumerate(train_data):
            anchor, label = corpus
            try:
                [loss, _, global_step, 
                accuracy, preds] = model.step(
                                    [anchor, label], 
                                    is_training=True)

                train_loss += loss*anchor.shape[0]
                train_accuracy += accuracy*anchor.shape[0]
                cnt += anchor.shape[0]
            except:
                continue

        train_loss /= float(cnt)
        train_accuracy /= float(cnt)

        info = OrderedDict()
        info["epoch"] = str(epoch)
        info["train_loss"] = str(train_loss)
        info["train_accuracy"] = str(train_accuracy)

        logger.info("epoch\t{}\ttrain\tloss\t{}\taccuracy\t{}".format(epoch, train_loss, train_accuracy))

        if train_accuracy > best_train_accuracy and train_loss < best_train_loss:
            timestamp = str(int(time.time()))
            model.save_model(os.path.join(model_dir, model_name, "models"), model_name+"_{}_{}_{}".format(timestamp, train_loss, train_accuracy))
            best_train_accuracy = train_accuracy
            best_train_loss = train_loss

            toleration_cnt = 0

            info["best_train_loss"] = str(best_train_loss)
            info["best_train_accuracy"] = str(best_train_accuracy)

            logger_utils.json_info(os.path.join(model_dir, model_name, "logs", "info.json"), info)
            logger.info("epoch\t{}\tbest_train\tloss\t{}\tbest_accuracy\t{}".format(epoch, train_loss, train_accuracy))
        else:
            toleration_cnt += 1

        if toleration_cnt >= toleration:
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, help='model name')
    parser.add_argument('--model_config', type=str, help='model config path')
    parser.add_argument('--model_dir', type=str, help='model path')
    parser.add_argument('--config_prefix', type=str, help='config path')
    parser.add_argument('--gpu_id', type=str, help='gpu id')
    parser.add_argument('--train_path', type=str, help='train data path')
    parser.add_argument('--dev_path', type=str, help='dev data path')
    parser.add_argument('--w2v_path', type=str, help='pretrained w2v path')
    parser.add_argument('--vocab_path', type=str, help='vocab_path')

    args, unparsed = parser.parse_known_args()
    model_config = args.model_config

    with open(model_config, "r") as frobj:
        model_config = json.load(frobj)

    config = {}
    config["model_dir"] = args.model_dir
    config["model"] = args.model
    config["model_config_path"] = os.path.join(args.config_prefix, 
                            model_config.get(args.model, "biblosa"))
    config["gpu_id"] = args.gpu_id
    config["train_path"] = args.train_path
    config["w2v_path"] = args.w2v_path
    config["vocab_path"] = args.vocab_path
    config["dev_path"] = args.dev_path
    
    train(config)


    










