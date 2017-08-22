import logging
import os
import queue
import urllib.request
import zipfile
from io import BytesIO, StringIO
from typing import Union

import numpy as np
import pandas as pd
import pylab
from sklearn.metrics import r2_score

logger = logging.getLogger('hybrid-lstm.tool')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s [%(name)s | %(levelname)s] %(message)s')

_cl = logging.StreamHandler()
_cl.setLevel(logging.DEBUG)
_cl.setFormatter(formatter)
logger.addHandler(_cl)


def preprocess(data: pd.DataFrame):
    # Lower column names
    COLUMNS = ['date', 'time', 'active_power', 'reactive_power', 'voltage', 'intensity', 'sub1', 'sub2', 'sub3']
    # data.columns = map(str.lower, data.columns)
    data.columns = COLUMNS

    # Datetime Index
    data['datetime'] = pd.to_datetime(data['date'] + ' ' + data['time'])
    data.set_index('datetime', inplace=True)
    del data['date']
    del data['time']

    # Diff: 그 다음 데이터와 시간적 차이 (초단위)
    # 예를 들어서 현재 00시 00분 이고, 다음이 00시 5분이라면 5분이라는 차이가 생기고,
    # 5 * 60 = 300초 시간만큼 00분 row에 넣는다.
    data['diff_next'] = pd.to_datetime(data.index)
    data['diff_next'] = data['diff_next'].diff(1).dt.total_seconds().shift(-1)

    # Filter only numeric Data
    data = data[data.applymap(np.isreal)].dropna()

    return data


def augment(data):
    n = len(data)
    shape = data.shape[1:]

    # Create Augmented Dataset
    aug = np.zeros((n * 3, *shape), dtype='float32')
    aug[:n] = data

    # Plus
    aug[n:n * 2] += 3  # np.std(data, axis=0)

    # Minus
    aug[n * 2:n * 3] -= 2  # np.std(data, axis=0)

    return aug


def load_household_power_consumption(dest='dataset'):
    """
    https://archive.ics.uci.edu/ml/datasets/Individual+household+electric+power+consumption

    1.date: Date in format dd/mm/yyyy
    2.time: time in format hh:mm:ss
    3.global_active_power: household global minute-averaged active power (in kilowatt)
    4.global_reactive_power: household global minute-averaged reactive power (in kilowatt)
    5.voltage: minute-averaged voltage (in volt)
    6.global_intensity: household global minute-averaged current intensity (in ampere)
    7.sub_metering_1: energy sub-metering No. 1 (in watt-hour of active energy). It corresponds to the kitchen, containing mainly a dishwasher, an oven and a microwave (hot plates are not electric but gas powered).
    8.sub_metering_2: energy sub-metering No. 2 (in watt-hour of active energy). It corresponds to the laundry room, containing a washing-machine, a tumble-drier, a refrigerator and a light.
    9.sub_metering_3: energy sub-metering No. 3 (in watt-hour of active energy). It corresponds to an electric water-heater and an air-conditioner.
    """
    URL = 'https://archive.ics.uci.edu/ml/machine-learning-databases/00235/household_power_consumption.zip'
    ZIP_FILE_NAME = 'household_power_consumption.txt'
    CSV_PATH = os.path.join('dataset', 'household_power_consumption.csv')

    ##################################
    # Check existing file
    ##################################
    if not os.path.exists(dest):
        os.mkdir(dest)

    ##################################
    # Download and Unzip file
    ##################################

    if not os.path.exists(CSV_PATH):
        logger.info('Started downloading dataset. It may take several minutes.')
        with urllib.request.urlopen(URL) as res:
            f = BytesIO(res.read())
            zip_ref = zipfile.ZipFile(f)
            data_txt = zip_ref.read(ZIP_FILE_NAME).decode('utf-8')
            zip_ref.close()
        logger.info('Preprocessing...')
        data = pd.read_csv(StringIO(data_txt), sep=';')
        data = preprocess(data)
        logger.info(f'Saved the dataset in "{CSV_PATH}"')
        data.to_csv(CSV_PATH)
    else:
        logger.info('Load existing dataset')
        data = pd.read_csv(CSV_PATH, index_col=0)

        data.index = pd.to_datetime(data.index)

    matrix: np.array = data.as_matrix()
    y = matrix[:, 0].reshape(-1, 1)
    x = matrix[:, 1:]
    return data, x, y


def to_timeseries(data: Union[pd.DataFrame, np.array], t=30):
    if isinstance(data, pd.DataFrame):
        data = data.as_matrix()

    deque = queue.deque(maxlen=t)

    timeseries = list()
    for i in range(len(data)):
        diff = data[i][-1]
        if diff >= 120:
            deque.clear()

        deque.append(data[i])
        if len(deque) == t:
            timeseries.append(deque.copy())

    return np.array(timeseries, dtype=np.float64)


def split_train_test(data_x, data_y, train_ratio=0.8):
    n = len(data_x)
    train_n = int(n * train_ratio)

    train_x, test_x = data_x[:train_n], data_x[train_n:]
    train_y, test_y = data_y[:train_n], data_y[train_n:]
    return train_x, train_y, test_x, test_y


def vis_evaluate(model, test_x, test_y):
    n = len(test_x)

    fig, plots = pylab.subplots(4, 4)
    plots = plots.reshape(-1)

    fig.set_figwidth(12)
    fig.set_figheight(7)

    for p in plots:
        idx = np.random.randint(0, n)
        true_y = test_y[idx]
        pred_y = model.predict(test_x[idx:idx + 1])

        score = r2_score(true_y.reshape(-1), pred_y.reshape(-1))
        print(f'[{idx:<4}] r^2: {score:<12.4}')
        p.plot(pred_y[0], color='red')
        p.plot(true_y)


if __name__ == '__main__':
    data = load_household_power_consumption()
    print([(c, data[c].dtype) for c in data.columns])
