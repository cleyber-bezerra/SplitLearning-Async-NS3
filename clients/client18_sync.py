'''
Shared Split learning (Client 18 -> Server -> Client 18)
Client 18 program
'''
import gc
from glob import escape
import os
from pyexpat import model
import socket
import struct
import pickle

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import torchvision.transforms as transforms
import torch.optim as optim
import time
import sys
import copy
from torch.autograd import Variable
from tqdm import tqdm
from torch.utils.data import Dataset, DataLoader
from time import process_time

# Adiciona o caminho da pasta onde o arquivo está localizado MyNet
file_path = os.path.abspath(os.path.join('.', 'nets'))
sys.path.append(file_path)

import MyNet
import socket_fun as sf

### global variable
### variável global
DAM = b'ok!'    # dammy
MODE = 0    # 0->train, 1->test

BATCH_SIZE = 128

print(" ------ CLIENT 18 ------")
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
# device = torch.device('cpu')
print("device: ", device)

#MNIST
root = './models/mnist_data'
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))  # Parâmetros de normalização para MNIST
])

# download dataset
trainset = torchvision.datasets.MNIST(root=root, download=True, train=True, transform=transform)
# if you want to divide dataset, remove comments below.
# se você deseja dividir o conjunto de dados, remova os comentários abaixo.
# indices = np.arange(len(trainset))
# train_dataset = torch.utils.data.Subset(
#     trainset, indices[0:20000]
# )
# trainset = train_dataset
testset = torchvision.datasets.MNIST(root=root, download=True, train=False, transform=transform)

print("trainset_len: ", len(trainset))
print("testset_len: ", len(testset))
image, label = trainset[0]
print (image.size())

trainloader = DataLoader(trainset, batch_size=BATCH_SIZE, shuffle=True, num_workers=2)
testloader = DataLoader(testset, batch_size=BATCH_SIZE, shuffle=False, num_workers=2)

mymodel1 = MyNet.MyNet_in().to(device)
mymodel2 = MyNet.MyNet_out(NUM_CLASSES=10).to(device)

# -------------------- connection ----------------------
# -------------------- conexão ----------------------
# socket establish
# estabelecimento de soquete
host = '127.0.0.1'
port = 19089
ADDR = (host, port)

# CONNECT
# CONECTAR
s = socket.socket()
s.connect(ADDR)
w = 'start communication'

# SEND
# ENVIAR
s.sendall(w.encode())
print("sent request to a server")
dammy = s.recv(4)

# ------------------ start training -----------------
# ------------------ comece a treinar -----------------
epochs = 1
lr = 0.005

# set error function
# define função de erro
criterion = nn.CrossEntropyLoss()

# set optimizer
# definir otimizador
optimizer1 = optim.SGD(mymodel1.parameters(), lr=lr, momentum=0.9, weight_decay=5e-4)
optimizer2 = optim.SGD(mymodel2.parameters(), lr=lr, momentum=0.9, weight_decay=5e-4)

# Variáveis para contabilizar a sobrecarga de comunicação
comm_time = 0
comm_data_size = 0

def train():
    global comm_time, comm_data_size

    # forward prop. function
    # suporte para frente. função
    def forward_prop(MODEL, data):

        output = None
        if MODEL == 1:
            optimizer1.zero_grad()
            output_1 = mymodel1(data)
            output = output_1
        elif MODEL == 2:
            optimizer2.zero_grad()
            output_2 = mymodel2(data)
            output = output_2
        else:
            print("!!!!! MODEL not found !!!!!")

        return output

    train_loss_list, train_acc_list, val_loss_list, val_acc_list = [], [], [], []
    p_time_list = []

    for e in range(epochs):
        print("--------------- Epoch: ", e, " --------------")
        train_loss = 0
        train_acc = 0
        val_loss = 0
        val_acc = 0

        p_start = process_time()
        # ================= train mode ================
        # ================= modo trem ================
        mymodel1.train()
        mymodel2.train()
        ### send MODE
        ### enviar MODO
        MODE = 0    # train mode -> 0:train, 1:test, 2:finished train, 3:finished test
        MODEL = 1   # train model
        for data, labels in tqdm(trainloader):
            # send MODE number
            # envia o número do MODO
            sf.send_size_n_msg(MODE, s)
        
            data = data.to(device)
            labels = labels.to(device)

            output_1 = forward_prop(MODEL, data)

            # SEND ----------- feature data 1 ---------------
            # ENVIAR ----------- dados do recurso 1 ---------------
            start_time = process_time()
            sf.send_size_n_msg(output_1, s)
            comm_time += process_time() - start_time
            comm_data_size += output_1.element_size() * output_1.nelement()

            ### wait for SERVER to calculate... ###
            ### espere o SERVIDOR calcular... ###

            # RECEIVE ------------ feature data 2 -------------
            # RECEBER ------------ dados do recurso 2 -------------
            start_time = process_time()
            recv_data2 = sf.recv_size_n_msg(s)
            comm_time += process_time() - start_time
            comm_data_size += recv_data2.element_size() * recv_data2.nelement()

            # recebe dados do recurso 2 -> MODEL=2
            MODEL = 2   # receive feature data 2 -> MODEL=2

            # start forward prop. 3
            # inicia a hélice para frente. 3
            OUTPUT = forward_prop(MODEL, recv_data2)

            loss = criterion(OUTPUT, labels)

            loss.backward()     # parts out-layer (peças da camada externa)

            optimizer2.step()

            # SEND ------------- grad 2 -----------
            # ENVIAR ------------- 2ª série -----------
            start_time = process_time()
            sf.send_size_n_msg(recv_data2.grad, s)
            comm_time += process_time() - start_time
            comm_data_size += recv_data2.grad.element_size() * recv_data2.grad.nelement()

            # RECEIVE ----------- grad 1 -----------
            # RECEBER ----------- 1ª série -----------
            start_time = process_time()
            recv_grad = sf.recv_size_n_msg(s)
            comm_time += process_time() - start_time
            comm_data_size += recv_grad.element_size() * recv_grad.nelement()

            MODEL = 1

            train_loss = train_loss + loss.item()
            train_acc += (OUTPUT.max(1)[1] == labels).sum().item()

            output_1.backward(recv_grad)    # parts in-layer (peças em camada)

            optimizer1.step()
        
        avg_train_loss = train_loss / len(trainloader.dataset)
        avg_train_acc = train_acc / len(trainloader.dataset)
        
        print("train mode finished!!!!")
        
        train_loss_list.append(avg_train_loss)
        train_acc_list.append(avg_train_acc)

        # =============== test mode ================
        # =============== modo de teste ================
        mymodel1.eval()
        mymodel2.eval()

        with torch.no_grad():
            print("start test mode!")
            MODE = 1    # change mode to test (mude o modo para testar)
            for data, labels in tqdm(testloader):
                # send MODE number
                # envia o número do MODO
                sf.send_size_n_msg(MODE, s)

                data = data.to(device)
                labels = labels.to(device)
                output = mymodel1(data)

                # SEND --------- feature data 1 -----------
                # ENVIAR --------- dados do recurso 1 -----------
                start_time = process_time()
                sf.send_size_n_msg(output, s)
                comm_time += process_time() - start_time
                comm_data_size += output.element_size() * output.nelement()

                ### wait for the server...
                ### espere pelo servidor...

                # RECEIVE ----------- feature data 2 ------------
                # RECEBER ----------- dados do recurso 2 ------------
                start_time = process_time()
                recv_data2 = sf.recv_size_n_msg(s)
                comm_time += process_time() - start_time
                comm_data_size += recv_data2.element_size() * recv_data2.nelement()

                OUTPUT = mymodel2(recv_data2)
                loss = criterion(OUTPUT, labels)

                val_loss += loss.item()
                val_acc += (OUTPUT.max(1)[1] == labels).sum().item()

        p_finish = process_time()
        p_time = p_finish-p_start
        if e == epochs-1:
            MODE = 3
            # sf.send_size_n_msg(MODE, s)     # per client ver.
        else:                                 # per epoch ver.
            MODE = 2    # finished test -> start next client's training
        sf.send_size_n_msg(MODE, s)           # per epoch ver.
        print("Processing time: ", p_time)
        p_time_list.append(p_time)

        avg_val_loss = val_loss / len(testloader.dataset)
        avg_val_acc = val_acc / len(testloader.dataset)
        
        print ('Epoch [{}/{}], Loss: {loss:.5f}, Acc: {acc:.5f},  val_loss: {val_loss:.5f}, val_acc: {val_acc:.5f}' 
                    .format(e+1, epochs, loss=avg_train_loss, acc=avg_train_acc, val_loss=avg_val_loss, val_acc=avg_val_acc))
        
        val_loss_list.append(avg_val_loss)
        val_acc_list.append(avg_val_acc)

        if e == epochs-1: 
            s.close()
            print("Finished the socket connection(CLIENT 18)")

    return train_loss_list, train_acc_list, val_loss_list, val_acc_list, p_time_list, comm_time, comm_data_size

import csv

def write_to_csv(train_loss_list, train_acc_list, val_loss_list, val_acc_list, p_time_list, comm_time, comm_data_size):
    file = './results/csv/ia/result_train_sync.csv'
    f = open(file, 'a', newline='')
    csv_writer = csv.writer(f)

    result = []
    result.append('client 18')
    result.append(train_loss_list)
    result.append(train_acc_list)
    result.append(val_loss_list)
    result.append(val_acc_list)
    result.append(p_time_list)
    result.append(comm_time)       
    result.append(comm_data_size)  

    csv_writer.writerow(result)

    f.close()

if __name__ == '__main__':
    train_loss_list, train_acc_list, val_loss_list, val_acc_list, p_time_list, comm_time, comm_data_size = train()
    write_to_csv(train_loss_list, train_acc_list, val_loss_list, val_acc_list, p_time_list, comm_time, comm_data_size)
