# Author: Hanzi Mao <hannamao15@gmail.com>
#
# License: BSD 3 clause

from .model import MLModel
from ..metrics import pearson_corr_as_scorer
from ..train_test_split import AdaptiveKFold

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import RandomizedSearchCV
from sklearn.model_selection import KFold
import numpy as np
from sklearn.model_selection import cross_val_score
from sklearn.metrics import make_scorer
from scipy.stats import randint
from scipy.stats import uniform
from smac.configspace import ConfigurationSpace
from ConfigSpace import UniformFloatHyperparameter, UniformIntegerHyperparameter
from smac.scenario.scenario import Scenario
from smac.facade.smac_facade import SMAC


def rmse(y, y_pred):
    return np.sqrt(np.mean((y_pred - y)**2))


class GradientBoostingModel(MLModel):
    def __init__(self, X_train, y_train, X_test, y_test, seed=192, param_dist=None):
        super(GradientBoostingModel, self).__init__(X_train, y_train, X_test, y_test)
        self.param_dist = param_dist
        self.seed = seed

    def _get_cv(self):
        cv_type = self.cv_type

        if cv_type == "kfold":
            return 10
        elif cv_type == "shuffle":
            return KFold(n_splits=10, shuffle=True, random_state=self.seed)

    def _get_scorer(self):
        scorer = self.scorer
        search_type = self.search_type

        if scorer == "r2":
            return "r2"
        elif scorer == "corr":
            return make_scorer(pearson_corr_as_scorer)
        elif scorer == "rmse":
            if search_type == "random":
                return "neg_mean_squared_error"
            elif search_type == "smac":
                return make_scorer(rmse, greater_is_better=False)

    def apply_model(self, feature_names, cv_type=None, search_type=None, scorer=None):
        self.cv_type = cv_type
        self.search_type = search_type
        self.scorer = scorer

        if cv_type is None:
            gb = GradientBoostingRegressor(learning_rate=0.1, n_estimators=300, random_state=self.seed)
            gb.fit(self.X_train, self.y_train)
        else:
            if search_type == "random":
                parameter_grid = self._get_random_parameter_grid()
                gb_search = RandomizedSearchCV(estimator=GradientBoostingRegressor(learning_rate=0.1,
                                                                                   n_estimators=300,
                                                                                   random_state=self.seed),
                                               param_distributions=parameter_grid,
                                               scoring=self._get_scorer(),
                                               n_iter=100,
                                               cv=self._get_cv(),
                                               iid=False,
                                               random_state=self.seed,
                                               n_jobs=-1)
                gb_search.fit(self.X_train, self.y_train)
                gb = gb_search.best_estimator_

                mean_test_score = gb_search.cv_results_["mean_test_score"]
                std_test_score = gb_search.cv_results_["std_test_score"]
                print(max(mean_test_score), std_test_score[np.argmax(mean_test_score)])
                print(gb)

            elif search_type == "smac":
                smac = self._get_smac()
                try:
                    incumbent = smac.optimize()
                finally:
                    incumbent = smac.solver.incumbent
                gb = GradientBoostingRegressor(learning_rate=0.1, n_estimators=300, random_state=self.seed,
                                               max_depth=incumbent["max_depth"],
                                               min_samples_split=incumbent["min_samples_split"],
                                               min_samples_leaf=incumbent["min_samples_leaf"],
                                               max_features=incumbent["max_features"],
                                               subsample=incumbent["subsample"])
                gb.fit(self.X_train, self.y_train)
                print(gb)
            else:
                raise ValueError("search_type must be either random or smac.")

        train_prediction, test_prediction = self.apply_predict(gb)
        return train_prediction, test_prediction

    def _get_random_parameter_grid(self):
        n_features = self.X_train.shape[1]

        max_depth = randint(5, 16)
        min_samples_split = randint(200, 1001)
        min_samples_leaf = randint(30, 71)
        max_features = range(1, n_features + 1)
        subsample = uniform(0.6, 0.3)

        return {'max_depth': max_depth,
                'min_samples_split': min_samples_split,
                'min_samples_leaf': min_samples_leaf,
                'max_features': max_features,
                'subsample': subsample}

    def _gb_from_cfg(self, cfg, seed):
        gbr = GradientBoostingRegressor(learning_rate=0.1,
                                        n_estimators=300,
                                        random_state=seed,
                                        max_depth=cfg["max_depth"],
                                        min_samples_split=cfg["min_samples_split"],
                                        min_samples_leaf=cfg["min_samples_leaf"],
                                        max_features=cfg["max_features"],
                                        subsample=cfg["subsample"])
        cv_score = cross_val_score(gbr, self.X_train, self.y_train, cv=self._get_cv(), scoring=self._get_scorer())

        return -1 * np.mean(cv_score)

    def _get_cfg(self):
        n_features = self.X_train.shape[1]

        cs = ConfigurationSpace()
        max_depth = UniformIntegerHyperparameter("max_depth", 5, 16, default_value=5)
        min_samples_split = UniformIntegerHyperparameter("min_samples_split", 200, 1000, default_value=200)
        min_samples_leaf = UniformIntegerHyperparameter("min_samples_leaf", 30, 70, default_value=30)
        max_features = UniformIntegerHyperparameter("max_features", 1, n_features, default_value=1)
        subsample = UniformFloatHyperparameter("subsample", 0.6, 0.9, default_value=0.6)

        cs.add_hyperparameters([max_depth, min_samples_split, min_samples_leaf, max_features, subsample])
        return cs

    def _get_smac(self):
        scenario = Scenario({"run_obj": "quality",  # we optimize quality (alternative runtime)
                             "runcount-limit": 100,  # maximum number of function evaluations
                             "cs": self._get_cfg(),  # configuration space
                             "deterministic": "true",
                             "memory_limit": 10000,  # adapt this to reasonable value for your hardware，
                             "output_dir": "SMAC"
                             })
        smac = SMAC(scenario=scenario, rng=np.random.RandomState(self.seed),
                    tae_runner=self._gb_from_cfg)
        return smac





