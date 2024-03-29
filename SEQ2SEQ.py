# -*- coding: gb2312 -*-


import argparse
import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from matplotlib import pyplot as plt
from torch.utils.data import DataLoader
from torch.utils.data import Dataset
from tqdm import tqdm
import torch.nn.functional as F
import os
# ���������
np.random.seed(0)


class StandardScaler():
    def __init__(self):
        self.mean = 0.
        self.std = 1.

    def fit(self, data):
        self.mean = data.mean(0)
        self.std = data.std(0)

    def transform(self, data):
        mean = torch.from_numpy(self.mean).type_as(data).to(data.device) if torch.is_tensor(data) else self.mean
        std = torch.from_numpy(self.std).type_as(data).to(data.device) if torch.is_tensor(data) else self.std
        return (data - mean) / std

    def inverse_transform(self, data):
        mean = torch.from_numpy(self.mean).type_as(data).to(data.device) if torch.is_tensor(data) else self.mean
        std = torch.from_numpy(self.std).type_as(data).to(data.device) if torch.is_tensor(data) else self.std
        if data.shape[-1] != mean.shape[-1]:
            mean = mean[-1:]
            std = std[-1:]
        return (data * std) + mean


def plot_loss_data(data):
    # ʹ��Matplotlib������ͼ
    plt.figure()
    plt.figure(figsize=(10, 5))
    plt.plot(data, marker='o')

    # ��ӱ���
    plt.title("loss results Plot")

    # ��ʾͼ��
    plt.legend(["Loss"])

    plt.show()


class TimeSeriesDataset(Dataset):
    def __init__(self, sequences):
        self.sequences = sequences

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, index):
        sequence, label = self.sequences[index]
        return torch.Tensor(sequence), torch.Tensor(label)


def create_inout_sequences(input_data, tw, pre_len, config):
    # ����ʱ����������ר�õ����ݷָ���
    inout_seq = []
    L = len(input_data)
    for i in range(L - tw):
        train_seq = input_data[i:i + tw]
        if (i + tw + pre_len) > len(input_data):
            break
        if config.feature == 'MS':
            train_label = input_data[:, -1:][i + tw:i + tw + pre_len]
        else:
            train_label = input_data[i + tw:i + tw + pre_len]
        inout_seq.append((train_seq, train_label))
    return inout_seq


def calculate_mae(y_true, y_pred):
    # ƽ���������
    mae = np.mean(np.abs(y_true - y_pred))
    return mae


def create_dataloader(config, device):
    print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>�������ݼ�����<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
    df = pd.read_csv(config.data_path)  # �����Լ������ݵ�ַ,�Զ�ѡȡ�����һ������Ϊ������ # �������ҪԤ���������
    pre_len = config.pre_len  # Ԥ��δ�����ݵĳ���
    train_window = config.window_size  # �۲ⴰ��

    # ���������Ƶ�ĩβ
    target_data = df[[config.target]]
    df = df.drop(config.target, axis=1)
    df = pd.concat((df, target_data), axis=1)

    cols_data = df.columns[1:]
    df_data = df[cols_data]

    # �����һЩ���ݵ�Ԥ����, �����Ҫ�ĸ�ʽ��pd.series
    true_data = df_data.values

    # �����׼���Ż���
    scaler = StandardScaler()
    scaler.fit(true_data)

    train_data = true_data[int(0.3 * len(true_data)):]
    valid_data = true_data[int(0.15 * len(true_data)):int(0.30 * len(true_data))]
    test_data = true_data[:int(0.15 * len(true_data))]
    print("ѵ�����ߴ�:", len(train_data), "���Լ��ߴ�:", len(test_data), "��֤���ߴ�:", len(valid_data))

    # ���б�׼������
    train_data_normalized = scaler.transform(train_data)
    test_data_normalized = scaler.transform(test_data)
    valid_data_normalized = scaler.transform(valid_data)

    # ת��Ϊ���ѧϰģ����Ҫ������Tensor
    train_data_normalized = torch.FloatTensor(train_data_normalized).to(device)
    test_data_normalized = torch.FloatTensor(test_data_normalized).to(device)
    valid_data_normalized = torch.FloatTensor(valid_data_normalized).to(device)

    # ����ѵ�����ĵ�����
    train_inout_seq = create_inout_sequences(train_data_normalized, train_window, pre_len, config)
    test_inout_seq = create_inout_sequences(test_data_normalized, train_window, pre_len, config)
    valid_inout_seq = create_inout_sequences(valid_data_normalized, train_window, pre_len, config)

    # �������ݼ�
    train_dataset = TimeSeriesDataset(train_inout_seq)
    test_dataset = TimeSeriesDataset(test_inout_seq)
    valid_dataset = TimeSeriesDataset(valid_inout_seq)

    # ���� DataLoader
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, drop_last=True)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, drop_last=True)
    valid_loader = DataLoader(valid_dataset, batch_size=args.batch_size, shuffle=False, drop_last=True)

    print("ͨ���������ڹ���ѵ�������ݣ�", len(train_inout_seq), "ת��Ϊ��������:", len(train_loader))
    print("ͨ���������ڹ��в��Լ����ݣ�", len(test_inout_seq), "ת��Ϊ��������:", len(test_loader))
    print("ͨ���������ڹ�����֤�����ݣ�", len(valid_inout_seq), "ת��Ϊ��������:", len(valid_loader))
    print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>�������ݼ��������<<<<<<<<<<<<<<<<<<<<<<<<<<<")
    return train_loader, test_loader, valid_loader, scaler


class LSTMEncoder(nn.Module):
    def __init__(self, rnn_num_layers=1, input_feature_len=1, sequence_len=168, hidden_size=100, bidirectional=False):
        super().__init__()
        self.sequence_len = sequence_len
        self.hidden_size = hidden_size
        self.input_feature_len = input_feature_len
        self.num_layers = rnn_num_layers
        self.rnn_directions = 2 if bidirectional else 1
        self.lstm = nn.LSTM(
            num_layers=rnn_num_layers,
            input_size=input_feature_len,
            hidden_size=hidden_size,
            batch_first=True,
            bidirectional=bidirectional
        )

    def forward(self, input_seq):

        ht = torch.zeros(self.num_layers * self.rnn_directions, input_seq.size(0), self.hidden_size, device='cuda')
        ct = ht.clone()
        if input_seq.ndim < 3:
            input_seq.unsqueeze_(2)
        lstm_out, (ht, ct) = self.lstm(input_seq, (ht, ct))
        if self.rnn_directions > 1:
            lstm_out = lstm_out.view(input_seq.size(0), self.sequence_len, self.rnn_directions, self.hidden_size)
            lstm_out = torch.sum(lstm_out, axis=2)
        return lstm_out, ht.squeeze(0)


class AttentionDecoderCell(nn.Module):
    def __init__(self, input_feature_len, out_put, sequence_len, hidden_size):
        super().__init__()
        # attention - inputs - (decoder_inputs, prev_hidden)
        self.attention_linear = nn.Linear(hidden_size + input_feature_len, sequence_len)
        # attention_combine - inputs - (decoder_inputs, attention * encoder_outputs)
        self.decoder_rnn_cell = nn.LSTMCell(
            input_size=hidden_size,
            hidden_size=hidden_size,
        )
        self.out = nn.Linear(hidden_size, input_feature_len)

    def forward(self, encoder_output, prev_hidden, y):
        if prev_hidden.ndimension() == 3:
            prev_hidden = prev_hidden[-1]  # �������һ�����Ϣ
        attention_input = torch.cat((prev_hidden, y), axis=1)
        attention_weights = F.softmax(self.attention_linear(attention_input), dim=-1).unsqueeze(1)
        attention_combine = torch.bmm(attention_weights, encoder_output).squeeze(1)
        rnn_hidden, rnn_hidden = self.decoder_rnn_cell(attention_combine, (prev_hidden, prev_hidden))
        output = self.out(rnn_hidden)
        return output, rnn_hidden


class EncoderDecoderWrapper(nn.Module):
    def __init__(self, input_size, output_size, hidden_size, num_layers, pred_len, window_size, teacher_forcing=0.3):
        super().__init__()
        self.encoder = LSTMEncoder(num_layers, input_size, window_size, hidden_size)
        self.decoder_cell = AttentionDecoderCell(input_size, output_size, window_size, hidden_size)
        self.output_size = output_size
        self.input_size = input_size
        self.pred_len = pred_len
        self.teacher_forcing = teacher_forcing
        self.linear = nn.Linear(input_size, output_size)

    def __call__(self, xb, yb=None):
        input_seq = xb
        encoder_output, encoder_hidden = self.encoder(input_seq)
        prev_hidden = encoder_hidden
        if torch.cuda.is_available():
            outputs = torch.zeros(self.pred_len, input_seq.size(0), self.input_size, device='cuda')
        else:
            outputs = torch.zeros(input_seq.size(0), self.output_size)
        y_prev = input_seq[:, -1, :]
        for i in range(self.pred_len):
            if (yb is not None) and (i > 0) and (torch.rand(1) < self.teacher_forcing):
                y_prev = yb[:, i].unsqueeze(1)
            rnn_output, prev_hidden = self.decoder_cell(encoder_output, prev_hidden, y_prev)
            y_prev = rnn_output
            outputs[i, :, :] = rnn_output
        outputs = outputs.permute(1, 0, 2)
        if self.output_size == 1:
            outputs = self.linear(outputs)
        return outputs


def train(model, args, scaler, device):
    start_time = time.time()  # ������ʼʱ��
    model = model
    loss_function = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    epochs = args.epochs
    model.train()  # ѵ��ģʽ
    results_loss = []
    for i in tqdm(range(epochs)):
        losss = []
        for seq, labels in train_loader:
            optimizer.zero_grad()

            y_pred = model(seq)

            single_loss = loss_function(y_pred, labels)

            single_loss.backward()

            optimizer.step()
            losss.append(single_loss.detach().cpu().numpy())
        tqdm.write(f"\t Epoch {i + 1} / {epochs}, Loss: {sum(losss) / len(losss)}")
        results_loss.append(sum(losss) / len(losss))

        torch.save(model.state_dict(), 'save_model.pth')
        time.sleep(0.1)


    # ��δ����ѧϰ�ʼƻ����ڲ���
    # ����ģ��

    print(f">>>>>>>>>>>>>>>>>>>>>>ģ���ѱ���,��ʱ:{(time.time() - start_time) / 60:.4f} min<<<<<<<<<<<<<<<<<<")
    plot_loss_data(results_loss)


def valid(model, args, scaler, valid_loader):
    lstm_model = model
    # ����ģ�ͽ���Ԥ��
    lstm_model.load_state_dict(torch.load('save_model.pth'))
    lstm_model.eval()  # ����ģʽ
    losss = []

    for seq, labels in valid_loader:
        pred = lstm_model(seq)
        mae = calculate_mae(pred.detach().numpy().cpu(), np.array(labels.detach().cpu()))  # MAE���������ֵ(Ԥ��ֵ  - ��ʵֵ)
        losss.append(mae)

    print("��֤�����MAE:", losss)
    return sum(losss) / len(losss)


def test(model, args, test_loader, scaler):
    # ����ģ�ͽ���Ԥ��
    losss = []
    model = model
    model.load_state_dict(torch.load('save_model.pth'))
    model.eval()  # ����ģʽ
    results = []
    labels = []
    for seq, label in test_loader:
        pred = model(seq)
        mae = calculate_mae(pred.detach().cpu().numpy(),
                            np.array(label.detach().cpu()))  # MAE���������ֵ(Ԥ��ֵ  - ��ʵֵ)
        losss.append(mae)
        pred = pred[:, 0, :]
        label = label[:, 0, :]
        pred = scaler.inverse_transform(pred.detach().cpu().numpy())
        label = scaler.inverse_transform(label.detach().cpu().numpy())
        for i in range(len(pred)):
            results.append(pred[i][-1])
            labels.append(label[i][-1])
    plt.figure(figsize=(10, 5))
    print("���Լ����MAE:", losss)
    # ������ʷ����
    plt.plot(labels, label='TrueValue')

    # ����Ԥ������
    # ע������Ԥ�����ݵ���ʼx��������ʷ���ݵ����һ�����x����
    plt.plot(results, label='Prediction')

    # ��ӱ����ͼ��
    plt.title("test state")
    plt.legend()
    plt.show()


# ����ģ��������
def inspect_model_fit(model, args, train_loader, scaler):
    model = model
    model.load_state_dict(torch.load('save_model.pth'))
    model.eval()  # ����ģʽ
    results = []
    labels = []

    for seq, label in train_loader:
        pred = model(seq)[:, 0, :]
        label = label[:, 0, :]
        pred = scaler.inverse_transform(pred.detach().cpu().numpy())
        label = scaler.inverse_transform(label.detach().cpu().numpy())
        for i in range(len(pred)):
            results.append(pred[i][-1])
            labels.append(label[i][-1])
    plt.figure(figsize=(10, 5))
    # ������ʷ����
    plt.plot(labels, label='History')

    # ����Ԥ������
    # ע������Ԥ�����ݵ���ʼx��������ʷ���ݵ����һ�����x����
    plt.plot(results, label='Prediction')

    # ��ӱ����ͼ��
    plt.title("inspect model fit state")
    plt.legend()
    plt.show()


def predict(model=None, args=None, device=None, scaler=None, rolling_data=None, show=False):
    # Ԥ��δ֪���ݵĹ���
    df = pd.read_csv(args.data_path)
    df = pd.concat((df, rolling_data), axis=0).reset_index(drop=True)
    df = df.iloc[:, 1:][-args.window_size:].values  # ת��Ϊnadarry
    pre_data = scaler.transform(df)
    tensor_pred = torch.FloatTensor(pre_data).to(device)
    tensor_pred = tensor_pred.unsqueeze(0)  # ����Ԥ�� , ����Ԥ�⹦����δ�������ڲ���
    model = model
    model.load_state_dict(torch.load('save_model.pth'))
    model.eval()  # ����ģʽ

    pred = model(tensor_pred)[0]

    pred = scaler.inverse_transform(pred.detach().cpu().numpy())
    if show:
        # ������ʷ���ݵĳ���
        history_length = len(df[:, -1])
        # Ϊ��ʷ��������x������
        history_x = range(history_length)
        plt.figure(figsize=(10, 5))
        # ΪԤ����������x������
        # ��ʼ����ʷ���ݵ����һ�����x����
        prediction_x = range(history_length - 1, history_length + len(pred[:, -1]) - 1)

        # ������ʷ����
        plt.plot(history_x, df[:, -1], label='History')

        # ����Ԥ������
        # ע������Ԥ�����ݵ���ʼx��������ʷ���ݵ����һ�����x����
        plt.plot(prediction_x, pred[:, -1], marker='o', label='Prediction')
        plt.axvline(history_length - 1, color='red')  # ��ͼ���xλ�ô���һ����ɫ����
        # ��ӱ����ͼ��
        plt.title("History and Prediction")
        plt.legend()
    return pred


def rolling_predict(model=None, args=None, device=None, scaler=None):
    # ����Ԥ��
    history_data = pd.read_csv(args.data_path)[args.target][-args.window_size * 4:].reset_index(drop=True)
    pre_data = pd.read_csv(args.roolling_data_path)
    columns = pre_data.columns[1:]
    columns = ['forecast' + column for column in columns]
    dict_of_lists = {column: [] for column in columns}
    results = []
    for i in range(int(len(pre_data) / args.pre_len)):
        rolling_data = pre_data.iloc[:args.pre_len * i]  # ת��Ϊnadarry
        pred = predict(model, args, device, scaler, rolling_data)
        if args.feature == 'MS' or args.feature == 'S':
            for i in range(args.pred_len):
                results.append(pred[i][0].detach().cpu().numpy())
        else:
            for j in range(args.output_size):
                for i in range(args.pre_len):
                    dict_of_lists[columns[j]].append(pred[i][j])
        print(pred)
    if args.feature == 'MS' or args.feature == 'S':
        df = pd.DataFrame({'date': pre_data['date'], '{}'.format(args.target): pre_data[args.target],
                           'forecast{}'.format(args.target): pre_data[args.target]})
        df.to_csv('Interval-{}'.format(args.data_path), index=False)
    else:
        df = pd.DataFrame(dict_of_lists)
        new_df = pd.concat((pre_data, df), axis=1)
        new_df.to_csv('Interval-{}'.format(args.data_path), index=False)
    pre_len = len(dict_of_lists['forecast' + args.target])
    # ��ͼ
    plt.figure()
    if args.feature == 'MS' or args.feature == 'S':
        plt.plot(range(len(history_data)), history_data,
                 label='Past Actual Values')
        plt.plot(range(len(history_data), len(history_data) + pre_len), pre_data[args.target][:pre_len].tolist(),
                 label='Predicted Actual Values')
        plt.plot(range(len(history_data), len(history_data) + pre_len), results, label='Predicted Future Values')
    else:
        plt.plot(range(len(history_data)), history_data,
                 label='Past Actual Values')
        plt.plot(range(len(history_data), len(history_data) + pre_len), pre_data[args.target][:pre_len].tolist(),
                 label='Predicted Actual Values')
        plt.plot(range(len(history_data), len(history_data) + pre_len), dict_of_lists['forecast' + args.target],
                 label='Predicted Future Values')
    # ���ͼ��
    plt.legend()
    plt.style.use('ggplot')
    # ��ӱ�������ǩ
    plt.title('Past vs Predicted Future Values')
    plt.xlabel('Time Point')
    plt.ylabel('Value')
    # ���ض�����λ�û�һ��ֱ��
    plt.axvline(x=len(history_data), color='blue', linestyle='--', linewidth=2)
    # ��ʾͼ��
    plt.savefig('forcast.png')
    plt.show()





if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Time Series forecast')
    parser.add_argument('-model', type=str, default='LSTM2LSTM', help="ģ������")
    parser.add_argument('-window_size', type=int, default=64, help="ʱ�䴰�ڴ�С, window_size > pre_len")
    parser.add_argument('-pre_len', type=int, default=24, help="Ԥ��δ�����ݳ���")
    # data
    parser.add_argument('-shuffle', action='store_true', default=True, help="�Ƿ�������ݼ������е�����˳��")
    parser.add_argument('-data_path', type=str, default='sf.csv', help="�������ݵ�ַ")
    parser.add_argument('-target', type=str, default='SapFlow', help='��ҪԤ��������У����ֵ����󱣴���csv�ļ���')
    parser.add_argument('-input_size', type=int, default=10, help='������������ʱ����һ��')
    parser.add_argument('-feature', type=str, default='M', help='[M, S, MS],��ԪԤ���Ԫ,��ԪԤ�ⵥԪ,��ԪԤ�ⵥԪ')

    # learning
    parser.add_argument('-lr', type=float, default=0.001, help="ѧϰ��")
    parser.add_argument('-drop_out', type=float, default=0.05, help="�����������,��ֹ�����")
    parser.add_argument('-epochs', type=int, default=10, help="ѵ���ִ�")
    parser.add_argument('-batch_size', type=int, default=16, help="���δ�С")
    parser.add_argument('-save_path', type=str, default='models')

    # model
    parser.add_argument('-hidden_size', type=int, default=128, help="���ز㵥Ԫ��")
    parser.add_argument('-laryer_num', type=int, default=2)

    # device
    parser.add_argument('-use_gpu', type=bool, default=True)
    parser.add_argument('-device', type=int, default=0, help="ֻ�������֧�ֵ���gpuѵ��")

    # option
    parser.add_argument('-train', type=bool, default=True)
    parser.add_argument('-test', type=bool, default=True)
    parser.add_argument('-predict', type=bool, default=True)
    parser.add_argument('-inspect_fit', type=bool, default=True)
    parser.add_argument('-lr-scheduler', type=bool, default=True)
    # ����Ԥ�⣬��Ҫ��һ��������ļ������ѵ�����ݼ���ȫ��ͬ��������ʱ��㲻ͬ��
    parser.add_argument('-rolling_predict', type=bool, default=True)
    parser.add_argument('-roolling_data_path', type=str, default='sf-Test.csv',
                        help="�������ݼ��ĵ�ַ")
    args = parser.parse_args()

    if isinstance(args.device, int) and args.use_gpu:
        device = torch.device("cuda:" + f'{args.device}')
    else:
        device = torch.device("cpu")
    print("ʹ���豸:", device)
    train_loader, test_loader, valid_loader, scaler = create_dataloader(args, device)

    if args.feature == 'MS' or args.feature == 'S':
        args.output_size = 1
    else:
        args.output_size = args.input_size

    # ʵ����ģ��
    try:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ��ʼ��{args.model}ģ��<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        model = EncoderDecoderWrapper(args.input_size, args.output_size, args.hidden_size, args.laryer_num,
                                      args.pre_len, args.window_size).to(device)
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ��ʼ��{args.model}ģ�ͳɹ�<<<<<<<<<<<<<<<<<<<<<<<<<<<")
    except:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ��ʼ��{args.model}ģ��ʧ��<<<<<<<<<<<<<<<<<<<<<<<<<<<")

    # ѵ��ģ��
    if args.train:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ{args.model}ģ��ѵ��<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        train(model, args, scaler, device)
    if args.test:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ{args.model}ģ�Ͳ���<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        test(model, args, test_loader, scaler)
    if args.inspect_fit:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>��ʼ����{args.model}ģ��������<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        inspect_model_fit(model, args, train_loader, scaler)
    if args.predict:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>Ԥ��δ��{args.pre_len}������<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        predict(model, args, device, scaler, show=True)
    if args.predict:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>����Ԥ��δ��{args.pre_len}������<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        rolling_predict(model, args, device, scaler)
    plt.show()