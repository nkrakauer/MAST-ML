"""
This module contains a collection of classes and methods for selecting features, and interfaces with scikit-learn feature
selectors. More information on scikit-learn feature selectors is available at:

http://scikit-learn.org/stable/modules/classes.html#module-sklearn.feature_selection
"""

from functools import wraps
import warnings
import numpy as np
from mastml.metrics import root_mean_squared_error

import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.decomposition import PCA
import sklearn.feature_selection as fs
from mlxtend.feature_selection import SequentialFeatureSelector

from mastml.legos import util_legos

def dataframify_selector(transform):
    """
    Method which transforms output of scikit-learn feature selectors from array to dataframe. Enables preservation of column names.

    Args:

        transform: (function), a scikit-learn feature selector that has a transform method

    Returns:

        new_transform: (function), an amended version of the transform method that returns a dataframe

    """

    @wraps(transform)
    def new_transform(self, df):
        if isinstance(df, pd.DataFrame):
            return df[df.columns[self.get_support(indices=True)]]
        else: # just in case you try to use it with an array ;)
            return df
    return new_transform

def dataframify_new_column_names(transform, name):
    """
    Method which transforms output of scikit-learn feature selectors to dataframe, and adds column names

    Args:

        transform: (function), a scikit-learn feature selector that has a transform method

        name: (str), name of the feature selector

    Returns:

        new_transform: (function), an amended version of the transform method that returns a dataframe

    """

    def new_transform(self, df):
        arr = transform(self, df.values)
        labels = [name+str(i) for i in range(arr.shape[1])]
        return pd.DataFrame(arr, columns=labels)
    return new_transform

def fitify_just_use_values(fit):
    """
    Method which enables a feature selector fit method to operate on dataframes

    Args:

        fit: (function), a scikit-learn feature selector object with a fit method

    Returns:

        new_fit: (function), an amended version of the fit method that uses dataframes as input

    """

    def new_fit(self, X_df, y_df):
        return fit(self, X_df.values, y_df.values)
    return new_fit

score_func_selectors = {
    'GenericUnivariateSelect': fs.GenericUnivariateSelect, # Univariate feature selector with configurable strategy.
    'SelectFdr': fs.SelectFdr, # Filter: Select the p-values for an estimated false discovery rate
    'SelectFpr': fs.SelectFpr, # Filter: Select the pvalues below alpha based on a FPR test.
    'SelectFwe': fs.SelectFwe, # Filter: Select the p-values corresponding to Family-wise error rate
    'SelectKBest': fs.SelectKBest, # Select features according to the k highest scores.
    'SelectPercentile': fs.SelectPercentile, # Select features according to a percentile of the highest scores.
}

model_selectors = { # feature selectors which take a model instance as first parameter
    'RFE': fs.RFE, # Feature ranking with recursive feature elimination.
    'RFECV': fs.RFECV, # Feature ranking with recursive feature elimination and cross-validated selection of the best number of features.
    'SelectFromModel': fs.SelectFromModel, # Meta-transformer for selecting features based on importance weights.
}

other_selectors = {
    'VarianceThreshold': fs.VarianceThreshold, # Feature selector that removes all low-variance features.
}

# Union together the above dicts for the primary export:
name_to_constructor = dict(**score_func_selectors, **model_selectors, **other_selectors)

# Modify all sklearn transform methods to return dataframes:
for constructor in name_to_constructor.values():
    constructor.old_transform = constructor.transform
    constructor.transform = dataframify_selector(constructor.transform)

# TODO: Not used anymore, now uses util_legos.DoNothing
"""
class PassThrough(BaseEstimator, TransformerMixin):


    def __init__(self, features):
        print(features)
        print(type(features))
        exit()

        if not isinstance(features, list):
            features = [features]
        self.features = features

    def fit(self, df, y=None):
        for feature in self.features:
            if feature not in df.columns:
                raise Exception(f"Specified feature '{feature}' to PassThrough not present in data file.")

    def transform(self, df):
        return df[self.features]
"""

class MASTMLFeatureSelector(object):
    """
    Class custom-written for MAST-ML to conduct forward selection of features with flexible model and cv scheme

    Args:

        estimator: (scikit-learn model/estimator object), a scikit-learn model/estimator

        n_features_to_select: (int), the number of features to select

        cv: (scikit-learn cross-validation object), a scikit-learn cross-validation object

    Methods:

        fit: performs feature selection

            Args:

                X: (dataframe), dataframe of X features

                y: (dataframe), dataframe of y data

                Xgroups: (dataframe), dataframe of group labels

            Returns:

                None

        transform: performs the transform to generate output of only selected features

            Args:

                X: (dataframe), dataframe of X features

            Returns:

                dataframe: (dataframe), dataframe of selected X features

    """

    def __init__(self, estimator, n_features_to_select, cv):
        self.estimator = estimator
        self.n_features_to_select = n_features_to_select
        self.cv = cv

    def fit(self, X, y, Xgroups=None):
        if Xgroups.shape[0] == 0:
            xgroups = np.zeros(len(y))
            Xgroups = pd.DataFrame(xgroups)

        self.selected_feature_names = list()
        selected_feature_avg_rmses = list()
        selected_feature_std_rmses = list()
        basic_forward_selection_dict = dict()
        num_features_selected = 0
        x_features = X.columns.tolist()
        if self.n_features_to_select >= len(x_features):
            self.n_features_to_select = len(x_features)
        while num_features_selected < self.n_features_to_select:
            # Catch pandas warnings here
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                ranked_features = self._rank_features(X=X, y=y, groups=Xgroups)
                top_feature_name, top_feature_avg_rmse, top_feature_std_rmse = self._choose_top_feature(ranked_features=ranked_features)

            self.selected_feature_names.append(top_feature_name)
            selected_feature_avg_rmses.append(top_feature_avg_rmse)
            selected_feature_std_rmses.append(top_feature_std_rmse)

            basic_forward_selection_dict[str(num_features_selected)] = dict()
            basic_forward_selection_dict[str(num_features_selected)][
                'Number of features selected'] = num_features_selected + 1
            basic_forward_selection_dict[str(num_features_selected)][
                'Top feature added this iteration'] = top_feature_name
            basic_forward_selection_dict[str(num_features_selected)][
                'Avg RMSE using top features'] = top_feature_avg_rmse
            basic_forward_selection_dict[str(num_features_selected)][
                'Stdev RMSE using top features'] = top_feature_std_rmse
            num_features_selected += 1
        basic_forward_selection_dict[str(self.n_features_to_select - 1)][
            'Full feature set Names'] = self.selected_feature_names
        basic_forward_selection_dict[str(self.n_features_to_select - 1)][
            'Full feature set Avg RMSEs'] = selected_feature_avg_rmses
        basic_forward_selection_dict[str(self.n_features_to_select - 1)][
            'Full feature set Stdev RMSEs'] = selected_feature_std_rmses
        #self._plot_featureselected_learningcurve(selected_feature_avg_rmses=selected_feature_avg_rmses,
        #                                         selected_feature_std_rmses=selected_feature_std_rmses)
        return self

    def transform(self, X):
        dataframe = self._get_featureselected_dataframe(X=X, selected_feature_names=self.selected_feature_names)
        return dataframe

    def _rank_features(self, X, y, groups):
        y = np.array(y).reshape(-1, 1)
        ranked_features = dict()
        trains_metrics = list()
        tests_metrics = list()
        if groups is not None:
            groups = groups.iloc[:,0].tolist()
        for col in X.columns:
            if col not in self.selected_feature_names:
                X_ = X.loc[:, self.selected_feature_names]
                X_ = np.array(pd.concat([X_, X[col]],axis=1))
                for trains, tests in self.cv.split(X_, y, groups):
                    self.estimator.fit(X_[trains], y[trains])
                    #predict_trains = self.estimator.predict(X_[trains])
                    predict_tests = self.estimator.predict(X_[tests])
                    #trains_metrics.append(root_mean_squared_error(y[trains], predict_trains))
                    tests_metrics.append(root_mean_squared_error(y[tests], predict_tests))
                avg_rmse = np.mean(tests_metrics)
                std_rmse = np.std(tests_metrics)
                ranked_features[col] = {"avg_rmse": avg_rmse, "std_rmse": std_rmse}
        return ranked_features

    def _choose_top_feature(self, ranked_features):
        feature_names = list()
        feature_avg_rmses = list()
        feature_std_rmses = list()
        feature_names_sorted = list()
        feature_std_rmses_sorted = list()
        # Make dict of ranked features into list for sorting
        for k, v in ranked_features.items():
            feature_names.append(k)
            for kk, vv in v.items():
                if kk == 'avg_rmse':
                    feature_avg_rmses.append(vv)
                if kk == 'std_rmse':
                    feature_std_rmses.append(vv)

        # Sort feature lists so RMSE goes from min to max
        feature_avg_rmses_sorted = sorted(feature_avg_rmses)
        for feature_avg_rmse in feature_avg_rmses_sorted:
            for k, v in ranked_features.items():
                if v['avg_rmse'] == feature_avg_rmse:
                    feature_names_sorted.append(k)
                    feature_std_rmses_sorted.append(v['std_rmse'])

        top_feature_name = feature_names_sorted[0]
        top_feature_avg_rmse = feature_avg_rmses_sorted[0]
        top_feature_std_rmse = feature_std_rmses_sorted[0]

        return top_feature_name, top_feature_avg_rmse, top_feature_std_rmse

    def _get_featureselected_dataframe(self, X, selected_feature_names):
        # Return dataframe containing only selected features
        X_selected = X.loc[:, selected_feature_names]
        return X_selected

    # TODO: Not used anymore
    #def _plot_featureselected_learningcurve(self, selected_feature_avg_rmses, selected_feature_std_rmses):
    #    from matplotlib import pyplot as plt
    #    plt.figure()
    #    plt.title('Basic forward selection learning curve')
    #    plt.grid()
    #    #savedir = self.configdict['General Setup']['save_path']
    #    Xdata = np.linspace(start=1, stop=self.n_features_to_select, num=5).tolist()
    #    ydata = selected_feature_avg_rmses
    #    yspread = selected_feature_std_rmses
    #    plt.plot(Xdata, ydata, '-o', color='r', label='Avg RMSE 10 tests 5-fold CV')
    #    plt.fill_between(Xdata, np.array(ydata) - np.array(yspread),
    #                     np.array(ydata) + np.array(yspread), alpha=0.1,
    #                     color="r")
    #    plt.xlabel("Number of features")
    #    plt.ylabel("RMSE")
    #    plt.legend(loc="best")
    #    plt.savefig(savedir + "/" + "basic_forward_selection_learning_curve_featurenumber.png", dpi=250)
    #    return

# Include Principal Component Analysis
PCA.transform = dataframify_new_column_names(PCA.transform, 'pca_')

# Include Sequential Forward Selector
SequentialFeatureSelector.transform = dataframify_new_column_names(SequentialFeatureSelector.transform, 'sfs_')
SequentialFeatureSelector.fit = fitify_just_use_values(SequentialFeatureSelector.fit)
model_selectors['SequentialFeatureSelector'] = SequentialFeatureSelector
name_to_constructor['SequentialFeatureSelector'] = SequentialFeatureSelector

# Custom selectors don't need to be dataframified
name_to_constructor.update({
    #'PassThrough': PassThrough,
    'DoNothing': util_legos.DoNothing,
    'PCA': PCA,
    'SequentialFeatureSelector': SequentialFeatureSelector,
    'MASTMLFeatureSelector' : MASTMLFeatureSelector,
})