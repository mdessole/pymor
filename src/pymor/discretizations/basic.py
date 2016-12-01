# -*- coding: utf-8 -*-
# This file is part of the pyMOR project (http://www.pymor.org).
# Copyright 2013-2016 pyMOR developers and contributors. All rights reserved.
# License: BSD 2-Clause License (http://opensource.org/licenses/BSD-2-Clause)

from pymor.algorithms.timestepping import TimeStepperInterface
from pymor.discretizations.interfaces import DiscretizationInterface
from pymor.operators.constructions import VectorOperator, induced_norm
from pymor.operators.interfaces import OperatorInterface
from pymor.tools.frozendict import FrozenDict
from pymor.vectorarrays.interfaces import VectorArrayInterface
from pymor.vectorarrays.numpy import NumpyVectorSpace


class DiscretizationBase(DiscretizationInterface):
    """Base class for |Discretizations| providing some common functionality."""

    sid_ignore = DiscretizationInterface.sid_ignore | {'visualizer'}
    special_operators = frozenset()

    def __init__(self, operators, products=None, estimator=None, visualizer=None,
                 cache_region=None, name=None, **kwargs):

        operators = {} if operators is None else dict(operators)

        # handle special operators
        for on in self.special_operators:
            # special operators may not already exist as attributes
            assert not hasattr(self, on)
            # special operators must be uniquely given
            assert kwargs[on] is None or on not in operators or kwargs[on] == operators[on]

            op = kwargs[on]
            if op is None:
                op = operators.get(on)

            assert op is None or isinstance(op, OperatorInterface)

            setattr(self, on, op)
            operators[on] = op

        self.operators = FrozenDict(operators)
        self.linear = all(op is None or op.linear for op in operators.values())
        self.products = FrozenDict(products or {})
        self.estimator = estimator
        self.visualizer = visualizer
        self.enable_caching(cache_region)
        self.name = name

        if products:
            for k, v in products.items():
                setattr(self, '{}_product'.format(k), v)
                setattr(self, '{}_norm'.format(k), induced_norm(v))

    def with_(self, **kwargs):
        assert set(kwargs.keys()) <= self.with_arguments

        # when an operators is not specified but a special operator contained in operators,
        # make sure that we use the old operators dict but with updated special operators
        kwargs.setdefault('operators',
                          dict(self.operators,
                               **{on: kwargs.get(on, getattr(self, on)) for on in self.special_operators}))

        # make sure we do not use old special operators in case operators is specified
        for on in self.special_operators:
            kwargs.setdefault(on, None)

        return super(DiscretizationBase, self).with_(**kwargs)

    def visualize(self, U, **kwargs):
        """Visualize a solution |VectorArray| U.

        Parameters
        ----------
        U
            The |VectorArray| from
            :attr:`~pymor.discretizations.interfaces.DiscretizationInterface.solution_space`
            that shall be visualized.
        kwargs
            See docstring of `self.visualizer.visualize`.
        """
        if self.visualizer is not None:
            self.visualizer.visualize(U, self, **kwargs)
        else:
            raise NotImplementedError('Discretization has no visualizer.')

    def estimate(self, U, mu=None):
        if self.estimator is not None:
            return self.estimator.estimate(U, mu=mu, discretization=self)
        else:
            raise NotImplementedError('Discretization has no estimator.')


class StationaryDiscretization(DiscretizationBase):
    """Generic class for discretizations of stationary problems.

    This class describes discrete problems given by the equation::

        L(u(μ), μ) = F(μ)

    with a linear functional F and a (possibly non-linear) operator L.

    Parameters
    ----------
    operator
        The |Operator| L.
    rhs
        The |Functional| F.
    products
        A dict of inner product |Operators| defined on the discrete space the
        problem is posed on. For each product a corresponding norm
        is added as a method of the discretization.
    operators
        A dict of additional |Operators| associated with the discretization.
    parameter_space
        The |ParameterSpace| for which the discrete problem is posed.
    estimator
        An error estimator for the problem. This can be any object with
        an `estimate(U, mu, discretization)` method. If `estimator` is
        not `None`, an `estimate(U, mu)` method is added to the
        discretization which will call `estimator.estimate(U, mu, self)`.
    visualizer
        A visualizer for the problem. This can be any object with
        a `visualize(U, discretization, ...)` method. If `visualizer`
        is not `None`, a `visualize(U, *args, **kwargs)` method is added
        to the discretization which forwards its arguments to the
        visualizer's `visualize` method.
    cache_region
        `None` or name of the |CacheRegion| to use.
    name
        Name of the discretization.

    Attributes
    ----------
    operator
        The |Operator| L. The same as `operators['operator']`.
    rhs
        The |Functional| F. The same as `operators['rhs']`.
    """

    special_operators = frozenset({'operator', 'rhs'})

    def __init__(self, operator=None, rhs=None, products=None, operators=None,
                 parameter_space=None, estimator=None, visualizer=None, cache_region=None, name=None):
        super().__init__(operator=operator, rhs=rhs,
                         operators=operators,
                         products=products,
                         estimator=estimator, visualizer=visualizer,
                         cache_region=cache_region, name=name)
        self.solution_space = self.operator.source
        self.build_parameter_type(self.operator, self.rhs)
        self.parameter_space = parameter_space
        assert self.operator.source == self.operator.range == self.rhs.source
        assert self.rhs.source == self.operator.source and self.rhs.range == NumpyVectorSpace(1) and self.rhs.linear

    def _solve(self, mu=None):
        mu = self.parse_parameter(mu)

        # explicitly checking if logging is disabled saves the str(mu) call
        if not self.logging_disabled:
            self.logger.info('Solving {} for {} ...'.format(self.name, mu))

        return self.operator.apply_inverse(self.rhs.as_source_array(mu), mu=mu)


class InstationaryDiscretization(DiscretizationBase):
    """Generic class for discretizations of instationary problems.

    This class describes instationary problems given by the equations::

        M * ∂_t u(t, μ) + L(u(μ), t, μ) = F(t, μ)
                                u(0, μ) = u_0(μ)

    for t in [0,T], where L is a (possibly non-linear) time-dependent
    |Operator|, F is a time-dependent linear |Functional|, and u_0 the
    initial data. The mass |Operator| M is assumed to be linear,
    time-independent and |Parameter|-independent.

    Parameters
    ----------
    T
        The final time T.
    initial_data
        The initial data `u_0`. Either a |VectorArray| of length 1 or
        (for the |Parameter|-dependent case) a vector-like |Operator|
        (i.e. a linear |Operator| with `source.dim == 1`) which
        applied to `NumpyVectorArray(np.array([1]))` will yield the
        initial data for a given |Parameter|.
    operator
        The |Operator| L.
    rhs
        The |Functional| F.
    mass
        The mass |Operator| `M`. If `None`, the identity is assumed.
    time_stepper
        The :class:`time-stepper <pymor.algorithms.timestepping.TimeStepperInterface>`
        to be used by :meth:`~pymor.discretizations.interfaces.DiscretizationInterface.solve`.
    num_values
        The number of returned vectors of the solution trajectory. If `None`, each
        intermediate vector that is calculated is returned.
    products
        A dict of product |Operators| defined on the discrete space the
        problem is posed on. For each product a corresponding norm
        is added as a method of the discretization.
    operators
        A dict of additional |Operators| associated with the discretization.
    parameter_space
        The |ParameterSpace| for which the discrete problem is posed.
    estimator
        An error estimator for the problem. This can be any object with
        an `estimate(U, mu, discretization)` method. If `estimator` is
        not `None`, an `estimate(U, mu)` method is added to the
        discretization which will call `estimator.estimate(U, mu, self)`.
    visualizer
        A visualizer for the problem. This can be any object with
        a `visualize(U, discretization, ...)` method. If `visualizer`
        is not `None`, a `visualize(U, *args, **kwargs)` method is added
        to the discretization which forwards its arguments to the
        visualizer's `visualize` method.
    cache_region
        `None` or name of the |CacheRegion| to use.
    name
        Name of the discretization.

    Attributes
    ----------
    T
        The final time T.
    initial_data
        The intial data u_0 given by a vector-like |Operator|. The same
        as `vector_operators['initial_data']`.
    operator
        The |Operator| L. The same as `operators['operator']`.
    rhs
        The |Functional| F. The same as `operators['rhs']`.
    mass
        The mass operator M. The same as `operators['mass']`.
    time_stepper
        The provided :class:`time-stepper <pymor.algorithms.timestepping.TimeStepperInterface>`.
    """

    special_operators = frozenset({'operator', 'mass', 'rhs', 'initial_data'})

    def __init__(self, T, initial_data=None, operator=None, rhs=None, mass=None, time_stepper=None, num_values=None,
                 products=None, operators=None, parameter_space=None, estimator=None, visualizer=None,
                 cache_region=None, name=None):

        if isinstance(initial_data, VectorArrayInterface):
            initial_data = VectorOperator(initial_data, name='initial_data')

        super().__init__(initial_data=initial_data, operator=operator, rhs=rhs, mass=mass,
                         operators=operators, products=products, estimator=estimator,
                         visualizer=visualizer, cache_region=cache_region, name=name)
        self.T = T
        self.solution_space = self.operator.source
        self.time_stepper = time_stepper
        self.num_values = num_values
        self.build_parameter_type(self.initial_data, self.operator, self.rhs, self.mass, provides={'_t': 0})
        self.parameter_space = parameter_space
        if hasattr(time_stepper, 'nt'):
            self.add_with_arguments = self.add_with_arguments | {'time_stepper_nt'}

        assert isinstance(time_stepper, TimeStepperInterface)
        assert self.initial_data.source == NumpyVectorSpace(1)
        assert self.operator.source == self.operator.range == self.initial_data.range
        assert self.rhs is None \
            or self.rhs.linear and self.rhs.source == self.operator.source and self.rhs.range == NumpyVectorSpace(1)
        assert self.mass is None \
            or self.mass.linear and self.mass.source == self.mass.range == self.operator.source

    def with_(self, **kwargs):
        assert set(kwargs.keys()) <= self.with_arguments
        assert 'time_stepper_nt' not in kwargs or 'time_stepper' not in kwargs
        if 'time_stepper_nt' in kwargs:
            kwargs['time_stepper'] = self.time_stepper.with_(nt=kwargs.pop('time_stepper_nt'))
        return super().with_(**kwargs)

    def _solve(self, mu=None):
        mu = self.parse_parameter(mu).copy()

        # explicitly checking if logging is disabled saves the expensive str(mu) call
        if not self.logging_disabled:
            self.logger.info('Solving {} for {} ...'.format(self.name, mu))

        mu['_t'] = 0
        U0 = self.initial_data.as_range_array(mu)
        return self.time_stepper.solve(operator=self.operator, rhs=self.rhs, initial_data=U0, mass=self.mass,
                                       initial_time=0, end_time=self.T, mu=mu, num_values=self.num_values)
