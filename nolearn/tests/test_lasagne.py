import pickle

import matplotlib.pyplot as plt
from mock import patch
from mock import Mock
from lasagne.layers import Conv2DLayer
from lasagne.layers import DenseLayer
from lasagne.layers import DropoutLayer
from lasagne.layers import MaxPool2DLayer
from lasagne.layers import InputLayer
from lasagne.nonlinearities import identity
from lasagne.nonlinearities import softmax
from lasagne.objectives import categorical_crossentropy
from lasagne.objectives import Objective
from lasagne.updates import nesterov_momentum
import numpy as np
import pytest
from sklearn.base import clone
from sklearn.datasets import load_boston
from sklearn.datasets import fetch_mldata
from sklearn.grid_search import GridSearchCV
from sklearn.metrics import accuracy_score
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler
from sklearn.utils import shuffle
import theano.tensor as T

from nolearn._compat import builtins


@pytest.fixture(scope='session')
def NeuralNet():
    from nolearn.lasagne import NeuralNet
    return NeuralNet


@pytest.fixture
def nn(NeuralNet):
    return NeuralNet([('input', object())], input_shape=(10, 10))


@pytest.fixture(scope='session')
def mnist():
    dataset = fetch_mldata('mnist-original')
    X, y = dataset.data, dataset.target
    X = X.astype(np.float32) / 255.0
    y = y.astype(np.int32)
    return shuffle(X, y, random_state=42)


@pytest.fixture(scope='session')
def boston():
    dataset = load_boston()
    X, y = dataset.data, dataset.target
    # X, y = make_regression(n_samples=100000, n_features=13)
    X = StandardScaler().fit_transform(X).astype(np.float32)
    y = y.reshape(-1, 1).astype(np.float32)
    return shuffle(X, y, random_state=42)


class _OnEpochFinished:
    def __call__(self, nn, train_history):
        self.train_history = train_history
        if len(train_history) > 1:
            raise StopIteration()


class TestLasagneFunctionalMNIST:
    @pytest.fixture(scope='session')
    def net(self, NeuralNet):
        return NeuralNet(
            layers=[
                ('input', InputLayer),
                ('hidden1', DenseLayer),
                ('dropout1', DropoutLayer),
                ('hidden2', DenseLayer),
                ('dropout2', DropoutLayer),
                ('output', DenseLayer),
                ],
            input_shape=(None, 784),
            output_num_units=10,
            output_nonlinearity=softmax,

            more_params=dict(
                hidden1_num_units=512,
                hidden2_num_units=512,
                ),

            update=nesterov_momentum,
            update_learning_rate=0.01,
            update_momentum=0.9,

            max_epochs=5,
            on_epoch_finished=[_OnEpochFinished()],
            )

    @pytest.fixture(scope='session')
    def net_fitted(self, net, mnist):
        X, y = mnist
        X_train, y_train = X[:10000], y[:10000]
        return net.fit(X_train, y_train)

    @pytest.fixture(scope='session')
    def y_pred(self, net_fitted, mnist):
        X, y = mnist
        X_test = X[60000:]
        return net_fitted.predict(X_test)

    def test_accuracy(self, net_fitted, mnist, y_pred):
        X, y = mnist
        y_test = y[60000:]
        assert accuracy_score(y_pred, y_test) > 0.85

    def test_train_history(self, net_fitted):
        history = net_fitted.train_history_
        assert len(history) == 2  # due to early stopping
        assert history[0]['valid_accuracy'] > 0.8
        assert history[1]['valid_accuracy'] > history[0]['valid_accuracy']
        assert set(history[0].keys()) == set([
            'dur', 'epoch', 'train_loss', 'train_loss_best',
            'valid_loss', 'valid_loss_best', 'valid_accuracy',
            ])

    def test_early_stopping(self, net_fitted):
        early_stopping = net_fitted.on_epoch_finished[0]
        assert early_stopping.train_history == net_fitted.train_history_

    @pytest.fixture
    def X_test(self, mnist):
        X, y = mnist
        return X[60000:]

    def test_pickle(self, net_fitted, X_test, y_pred):
        pickled = pickle.dumps(net_fitted, -1)
        net_loaded = pickle.loads(pickled)
        assert np.array_equal(net_loaded.predict(X_test), y_pred)

    def test_load_params_from_net(self, net, net_fitted, X_test, y_pred):
        net_loaded = clone(net)
        net_loaded.load_params_from(net_fitted)
        assert np.array_equal(net_loaded.predict(X_test), y_pred)

    def test_load_params_from_params_values(self, net, net_fitted,
                                            X_test, y_pred):
        net_loaded = clone(net)
        net_loaded.load_params_from(net_fitted.get_all_params_values())
        assert np.array_equal(net_loaded.predict(X_test), y_pred)

    def test_save_params_to_path(self, net, net_fitted, X_test, y_pred):
        path = '/tmp/test_lasagne_functional_mnist.params'
        net_fitted.save_params_to(path)
        net_loaded = clone(net)
        net_loaded.load_params_from(path)
        assert np.array_equal(net_loaded.predict(X_test), y_pred)


def test_lasagne_functional_grid_search(mnist, monkeypatch):
    # Make sure that we can satisfy the grid search interface.
    from nolearn.lasagne import NeuralNet

    nn = NeuralNet(
        layers=[],
        X_tensor_type=T.matrix,
        )

    param_grid = {
        'more_params': [{'hidden_num_units': 100}, {'hidden_num_units': 200}],
        'update_momentum': [0.9, 0.98],
        }
    X, y = mnist

    vars_hist = []

    def fit(self, X, y):
        vars_hist.append(vars(self).copy())
        return self

    with patch.object(NeuralNet, 'fit', autospec=True) as mock_fit:
        mock_fit.side_effect = fit
        with patch('nolearn.lasagne.NeuralNet.score') as score:
            score.return_value = 0.3
            gs = GridSearchCV(nn, param_grid, cv=2, refit=False, verbose=4)
            gs.fit(X, y)

    assert [entry['update_momentum'] for entry in vars_hist] == [
        0.9, 0.9, 0.98, 0.98] * 2
    assert [entry['more_params'] for entry in vars_hist] == (
        [{'hidden_num_units': 100}] * 4 +
        [{'hidden_num_units': 200}] * 4
        )


def test_clone():
    from nolearn.lasagne import NeuralNet
    from nolearn.lasagne import BatchIterator

    params = dict(
        layers=[
            ('input', InputLayer),
            ('hidden', DenseLayer),
            ('output', DenseLayer),
            ],
        input_shape=(100, 784),
        output_num_units=10,
        output_nonlinearity=softmax,

        more_params={
            'hidden_num_units': 100,
            },
        update=nesterov_momentum,
        update_learning_rate=0.01,
        update_momentum=0.9,

        regression=False,
        objective=Objective,
        objective_loss_function=categorical_crossentropy,
        batch_iterator_train=BatchIterator(batch_size=100),
        X_tensor_type=T.matrix,
        y_tensor_type=T.ivector,
        use_label_encoder=False,
        on_epoch_finished=None,
        on_training_finished=None,
        max_epochs=100,
        eval_size=0.1,
        verbose=0,
        )
    nn = NeuralNet(**params)

    nn2 = clone(nn)
    params1 = nn.get_params()
    params2 = nn2.get_params()

    for ignore in (
        'batch_iterator_train',
        'batch_iterator_test',
        'output_nonlinearity',
        'loss',
        'objective',
        'on_epoch_finished',
        'on_training_finished',
        'custom_score',
        ):
        for par in (params, params1, params2):
            par.pop(ignore, None)

    assert params == params1 == params2


def test_lasagne_functional_regression(boston):
    from nolearn.lasagne import NeuralNet

    X, y = boston

    nn = NeuralNet(
        layers=[
            ('input', InputLayer),
            ('hidden1', DenseLayer),
            ('output', DenseLayer),
            ],
        input_shape=(128, 13),
        hidden1_num_units=100,
        output_nonlinearity=identity,
        output_num_units=1,

        update_learning_rate=0.01,
        update_momentum=0.1,
        regression=True,
        max_epochs=50,
        )

    nn.fit(X[:300], y[:300])
    assert mean_absolute_error(nn.predict(X[300:]), y[300:]) < 3.0


class TestTrainTestSplit:
    def test_reproducable(self, nn):
        X, y = np.random.random((100, 10)), np.repeat([0, 1, 2, 3], 25)
        X_train1, X_valid1, y_train1, y_valid1 = nn.train_test_split(
            X, y, eval_size=0.2)
        X_train2, X_valid2, y_train2, y_valid2 = nn.train_test_split(
            X, y, eval_size=0.2)
        assert np.all(X_train1 == X_train2)
        assert np.all(y_valid1 == y_valid2)

    def test_eval_size_zero(self, nn):
        X, y = np.random.random((100, 10)), np.repeat([0, 1, 2, 3], 25)
        X_train, X_valid, y_train, y_valid = nn.train_test_split(
            X, y, eval_size=0.0)
        assert len(X_train) == len(X)
        assert len(y_train) == len(y)
        assert len(X_valid) == 0
        assert len(y_valid) == 0

    def test_eval_size_half(self, nn):
        X, y = np.random.random((100, 10)), np.repeat([0, 1, 2, 3], 25)
        X_train, X_valid, y_train, y_valid = nn.train_test_split(
            X, y, eval_size=0.51)
        assert len(X_train) + len(X_valid) == 100
        assert len(y_train) + len(y_valid) == 100
        assert len(X_train) > 45


class TestCheckForUnusedKwargs:
    def test_okay(self, NeuralNet):
        net = NeuralNet(
            layers=[('input', Mock), ('mylayer', Mock)],
            input_shape=(10, 10),
            mylayer_hey='hey',
            update_foo=1,
            update_bar=2,
            )
        net._create_iter_funcs = lambda *args: (1, 2, 3)
        net.initialize()

    def test_unused(self, NeuralNet):
        net = NeuralNet(
            layers=[('input', Mock), ('mylayer', Mock)],
            input_shape=(10, 10),
            mylayer_hey='hey',
            yourlayer_ho='ho',
            update_foo=1,
            update_bar=2,
            )
        net._create_iter_funcs = lambda *args: (1, 2, 3)

        with pytest.raises(ValueError) as err:
            net.initialize()
        assert str(err.value) == 'Unused kwarg: yourlayer_ho'


class TestInitializeLayers:
    def test_initialization(self, NeuralNet):
        input, hidden1, hidden2, output = [
            Mock(__name__='MockLayer') for i in range(4)]
        nn = NeuralNet(
            layers=[
                (input, {'shape': (10, 10), 'name': 'input'}),
                (hidden1, {'some': 'param', 'another': 'param'}),
                (hidden2, {}),
                (output, {'name': 'output'}),
                ],
            input_shape=(10, 10),
            mock1_some='iwin',
            )
        out = nn.initialize_layers(nn.layers)

        input.assert_called_with(
            name='input', shape=(10, 10))
        nn.layers_['input'] is input.return_value

        hidden1.assert_called_with(
            incoming=input.return_value, name='mock1',
            some='iwin', another='param')
        nn.layers_['mock1'] is hidden1.return_value

        hidden2.assert_called_with(
            incoming=hidden1.return_value, name='mock2')
        nn.layers_['mock2'] is hidden2.return_value

        output.assert_called_with(
            incoming=hidden2.return_value, name='output')

        assert out is nn.layers_['output']

    def test_initialization_legacy(self, NeuralNet):
        input, hidden1, hidden2, output = [
            Mock(__name__='MockLayer') for i in range(4)]
        nn = NeuralNet(
            layers=[
                ('input', input),
                ('hidden1', hidden1),
                ('hidden2', hidden2),
                ('output', output),
                ],
            input_shape=(10, 10),
            hidden1_some='param',
            )
        out = nn.initialize_layers(nn.layers)

        input.assert_called_with(
            name='input', shape=(10, 10))
        nn.layers_['input'] is input.return_value

        hidden1.assert_called_with(
            incoming=input.return_value, name='hidden1', some='param')
        nn.layers_['hidden1'] is hidden1.return_value

        hidden2.assert_called_with(
            incoming=hidden1.return_value, name='hidden2')
        nn.layers_['hidden2'] is hidden2.return_value

        output.assert_called_with(
            incoming=hidden2.return_value, name='output')

        assert out is nn.layers_['output']

    def test_diamond(self, NeuralNet):
        input, hidden1, hidden2, concat, output = [
            Mock(__name__='MockLayer') for i in range(5)]
        nn = NeuralNet(
            layers=[
                ('input', input),
                ('hidden1', hidden1),
                ('hidden2', hidden2),
                ('concat', concat),
                ('output', output),
                ],
            input_shape=(10, 10),
            hidden2_incoming='input',
            concat_incomings=['hidden1', 'hidden2'],
            )
        nn.initialize_layers(nn.layers)

        input.assert_called_with(name='input', shape=(10, 10))
        hidden1.assert_called_with(incoming=input.return_value, name='hidden1')
        hidden2.assert_called_with(incoming=input.return_value, name='hidden2')
        concat.assert_called_with(
            incomings=[hidden1.return_value, hidden2.return_value],
            name='concat'
            )
        output.assert_called_with(incoming=concat.return_value, name='output')


class TestCNNVisualizeFunctions:
    @pytest.fixture(scope='session')
    def X_train(self, mnist):
        X, y = mnist
        return X[:100].reshape(-1, 1, 28, 28)

    @pytest.fixture(scope='session')
    def y_train(self, mnist):
        X, y = mnist
        return y[:100]

    @pytest.fixture(scope='session')
    def net_fitted(self, NeuralNet, X_train, y_train):
        nn = NeuralNet(
            layers=[
                ('input', InputLayer),
                ('conv1', Conv2DLayer),
                ('conv2', Conv2DLayer),
                ('pool2', MaxPool2DLayer),
                ('output', DenseLayer),
                ],
            input_shape=(None, 1, 28, 28),
            output_num_units=10,
            output_nonlinearity=softmax,

            more_params=dict(
                conv1_filter_size=(5, 5), conv1_num_filters=16,
                conv2_filter_size=(3, 3), conv2_num_filters=16,
                pool2_pool_size=(8, 8),
                hidden1_num_units=16,
                ),

            update=nesterov_momentum,
            update_learning_rate=0.01,
            update_momentum=0.9,

            max_epochs=3,
            )

        return nn.fit(X_train, y_train)

    def test_plot_loss(self, net_fitted):
        from nolearn.lasagne.visualize import plot_loss
        plot_loss(net_fitted)
        plt.clf()
        plt.cla()

    def test_plot_conv_weights(self, net_fitted):
        from nolearn.lasagne.visualize import plot_conv_weights
        plot_conv_weights(net_fitted.layers_['conv1'])
        plot_conv_weights(net_fitted.layers_['conv2'], figsize=(1, 2))
        plt.clf()
        plt.cla()

    def test_plot_conv_activity(self, net_fitted, X_train):
        from nolearn.lasagne.visualize import plot_conv_activity
        plot_conv_activity(net_fitted.layers_['conv1'], X_train[:1])
        plot_conv_activity(net_fitted.layers_['conv2'], X_train[10:11],
                           figsize=(3, 4))
        plt.clf()
        plt.cla()

    def test_plot_occlusion(self, net_fitted, X_train, y_train):
        from nolearn.lasagne.visualize import plot_occlusion
        plot_occlusion(net_fitted, X_train[2:4], y_train[2:4],
                       square_length=3, figsize=(5, 5))
        plt.clf()
        plt.cla()


def test_print_log(mnist):
    from nolearn.lasagne import PrintLog

    nn = Mock(
        regression=False,
        custom_score=('my_score', 0.99),
        )

    train_history = [{
        'epoch': 1,
        'train_loss': 0.8,
        'valid_loss': 0.7,
        'train_loss_best': False,
        'valid_loss_best': False,
        'valid_accuracy': 0.9,
        'my_score': 0.99,
        'dur': 1.0,
        }]
    output = PrintLog().table(nn, train_history)
    assert output == """\
  epoch    train loss    valid loss    train/val    valid acc    my_score  dur
-------  ------------  ------------  -----------  -----------  ----------  -----
      1       0.80000       0.70000      1.14286      0.90000     0.99000  1.00s\
"""


class TestSaveWeights():
    @pytest.fixture
    def SaveWeights(self):
        from nolearn.lasagne import SaveWeights
        return SaveWeights

    def test_every_n_epochs_true(self, SaveWeights):
        train_history = [{'epoch': 9, 'valid_loss': 1.1}]
        nn = Mock()
        handler = SaveWeights('mypath', every_n_epochs=3)
        handler(nn, train_history)
        assert nn.save_params_to.call_count == 1
        nn.save_params_to.assert_called_with('mypath')

    def test_every_n_epochs_false(self, SaveWeights):
        train_history = [{'epoch': 9, 'valid_loss': 1.1}]
        nn = Mock()
        handler = SaveWeights('mypath', every_n_epochs=4)
        handler(nn, train_history)
        assert nn.save_params_to.call_count == 0

    def test_only_best_true_single_entry(self, SaveWeights):
        train_history = [{'epoch': 9, 'valid_loss': 1.1}]
        nn = Mock()
        handler = SaveWeights('mypath', only_best=True)
        handler(nn, train_history)
        assert nn.save_params_to.call_count == 1

    def test_only_best_true_two_entries(self, SaveWeights):
        train_history = [
            {'epoch': 9, 'valid_loss': 1.2},
            {'epoch': 10, 'valid_loss': 1.1},
            ]
        nn = Mock()
        handler = SaveWeights('mypath', only_best=True)
        handler(nn, train_history)
        assert nn.save_params_to.call_count == 1

    def test_only_best_false_two_entries(self, SaveWeights):
        train_history = [
            {'epoch': 9, 'valid_loss': 1.2},
            {'epoch': 10, 'valid_loss': 1.3},
            ]
        nn = Mock()
        handler = SaveWeights('mypath', only_best=True)
        handler(nn, train_history)
        assert nn.save_params_to.call_count == 0

    def test_with_path_interpolation(self, SaveWeights):
        train_history = [{'epoch': 9, 'valid_loss': 1.1}]
        nn = Mock()
        handler = SaveWeights('mypath-{epoch}-{timestamp}-{loss}.pkl')
        handler(nn, train_history)
        path = nn.save_params_to.call_args[0][0]
        assert path.startswith('mypath-0009-2')
        assert path.endswith('-1.1.pkl')

    def test_pickle(self, SaveWeights):
        train_history = [{'epoch': 9, 'valid_loss': 1.1}]
        nn = Mock()
        with patch('nolearn.lasagne.handlers.pickle') as pickle:
            with patch.object(builtins, 'open') as mock_open:
                handler = SaveWeights('mypath', every_n_epochs=3, pickle=True)
                handler(nn, train_history)

        mock_open.assert_called_with('mypath', 'wb')
        pickle.dump.assert_called_with(nn, mock_open().__enter__(), -1)
