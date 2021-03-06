# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Utilities for probability distributions."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import numpy as np

from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import check_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops


def assert_close(
    x, y, data=None, summarize=None, message=None, name="assert_close"):
  """Assert that that x and y are within machine epsilon of each other.

  Args:
    x: Numeric `Tensor`
    y: Numeric `Tensor`
    data: The tensors to print out if the condition is `False`. Defaults to
      error message and first few entries of `x` and `y`.
    summarize: Print this many entries of each tensor.
    message: A string to prefix to the default message.
    name: A name for this operation (optional).

  Returns:
    Op raising `InvalidArgumentError` if |x - y| > machine epsilon.
  """
  message = message or ""
  x = ops.convert_to_tensor(x, name="x")
  y = ops.convert_to_tensor(y, name="y")

  if x.dtype.is_integer:
    return check_ops.assert_equal(
        x, y, data=data, summarize=summarize, message=message, name=name)

  with ops.name_scope(name, "assert_close", [x, y, data]):
    tol = np.finfo(x.dtype.as_numpy_dtype).resolution
    if data is None:
      data = [
          message,
          "Condition x ~= y did not hold element-wise: x = ", x.name, x, "y = ",
          y.name, y
      ]
    condition = math_ops.reduce_all(math_ops.less_equal(math_ops.abs(x-y), tol))
    return control_flow_ops.Assert(
        condition, data, summarize=summarize)


def assert_integer_form(
    x, data=None, summarize=None, message=None, name="assert_integer_form"):
  """Assert that x has integer components (or floats equal to integers).

  Args:
    x: Numeric `Tensor`
    data: The tensors to print out if the condition is `False`. Defaults to
      error message and first few entries of `x` and `y`.
    summarize: Print this many entries of each tensor.
    message: A string to prefix to the default message.
    name: A name for this operation (optional).

  Returns:
    Op raising `InvalidArgumentError` if round(x) != x.
  """

  message = message or "x has non-integer components"
  x = ops.convert_to_tensor(x, name="x")
  casted_x = math_ops.to_int64(x)
  return check_ops.assert_equal(
      x, math_ops.cast(math_ops.round(casted_x), x.dtype),
      data=data, summarize=summarize, message=message, name=name)


def assert_symmetric(matrix):
  matrix_t = array_ops.batch_matrix_transpose(matrix)
  return control_flow_ops.with_dependencies(
      [check_ops.assert_equal(matrix, matrix_t)], matrix)


def get_logits_and_prob(
    logits=None, p=None,
    multidimensional=False, validate_args=False, name="GetLogitsAndProb"):
  """Converts logits to probabilities and vice-versa, and returns both.

  Args:
    logits: Numeric `Tensor` representing log-odds.
    p: Numeric `Tensor` representing probabilities.
    multidimensional: Given `p` a [N1, N2, ... k] dimensional tensor,
      whether the last dimension represents the probability between k classes.
      This will additionally assert that the values in the last dimension
      sum to one. If `False`, will instead assert that each value is in
      `[0, 1]`.
    validate_args: `Boolean`, default `False`.  Whether to assert `0 <= p <= 1`
      if multidimensional is `False`, otherwise that the last dimension of `p`
      sums to one.
    name: A name for this operation (optional).

  Returns:
    Tuple with `logits` and `p`. If `p` has an entry that is `0` or `1`, then
    the corresponding entry in the returned logits will be `-Inf` and `Inf`
    respectively.

  Raises:
    ValueError: if neither `p` nor `logits` were passed in, or both were.
  """
  with ops.name_scope(name, values=[p, logits]):
    if p is None and logits is None:
      raise ValueError("Must pass p or logits.")
    elif p is not None and logits is not None:
      raise ValueError("Must pass either p or logits, not both.")
    elif p is None:
      logits = array_ops.identity(logits, name="logits")
      with ops.name_scope("p"):
        p = math_ops.sigmoid(logits)
    elif logits is None:
      with ops.name_scope("p"):
        p = array_ops.identity(p)
        if validate_args:
          one = constant_op.constant(1., p.dtype)
          dependencies = [check_ops.assert_non_negative(p)]
          if multidimensional:
            dependencies += [assert_close(
                math_ops.reduce_sum(p, reduction_indices=[-1]),
                one, message="p does not sum to 1.")]
          else:
            dependencies += [check_ops.assert_less_equal(
                p, one, message="p has components greater than 1.")]
          p = control_flow_ops.with_dependencies(dependencies, p)
      with ops.name_scope("logits"):
        logits = math_ops.log(p) - math_ops.log(1. - p)
    return (logits, p)


def log_combinations(n, counts, name="log_combinations"):
  """Multinomial coefficient.

  Given `n` and `counts`, where `counts` has last dimension `k`, we compute
  the multinomial coefficient as:

  ```n! / sum_i n_i!```

  where `i` runs over all `k` classes.

  Args:
    n: Numeric `Tensor` broadcastable with `counts`. This represents `n`
      outcomes.
    counts: Numeric `Tensor` broadcastable with `n`. This represents counts
      in `k` classes, where `k` is the last dimension of the tensor.
    name: A name for this operation (optional).

  Returns:
    `Tensor` representing the multinomial coefficient between `n` and `counts`.
  """
  # First a bit about the number of ways counts could have come in:
  # E.g. if counts = [1, 2], then this is 3 choose 2.
  # In general, this is (sum counts)! / sum(counts!)
  # The sum should be along the last dimension of counts.  This is the
  # "distribution" dimension. Here n a priori represents the sum of counts.
  with ops.name_scope(name, values=[n, counts]):
    total_permutations = math_ops.lgamma(n + 1)
    counts_factorial = math_ops.lgamma(counts + 1)
    redundant_permutations = math_ops.reduce_sum(counts_factorial,
                                                 reduction_indices=[-1])
    return total_permutations - redundant_permutations


def batch_matrix_diag_transform(matrix, transform=None, name=None):
  """Transform diagonal of [batch-]matrix, leave rest of matrix unchanged.

  Create a trainable covariance defined by a Cholesky factor:

  ```python
  # Transform network layer into 2 x 2 array.
  matrix_values = tf.contrib.layers.fully_connected(activations, 4)
  matrix = tf.reshape(matrix_values, (batch_size, 2, 2))

  # Make the diagonal positive.  If the upper triangle was zero, this would be a
  # valid Cholesky factor.
  chol = batch_matrix_diag_transform(matrix, transform=tf.nn.softplus)

  # OperatorPDCholesky ignores the upper triangle.
  operator = OperatorPDCholesky(chol)
  ```

  Example of heteroskedastic 2-D linear regression.

  ```python
  # Get a trainable Cholesky factor.
  matrix_values = tf.contrib.layers.fully_connected(activations, 4)
  matrix = tf.reshape(matrix_values, (batch_size, 2, 2))
  chol = batch_matrix_diag_transform(matrix, transform=tf.nn.softplus)

  # Get a trainable mean.
  mu = tf.contrib.layers.fully_connected(activations, 2)

  # This is a fully trainable multivariate normal!
  dist = tf.contrib.distributions.MVNCholesky(mu, chol)

  # Standard log loss.  Minimizing this will "train" mu and chol, and then dist
  # will be a distribution predicting labels as multivariate Gaussians.
  loss = -1 * tf.reduce_mean(dist.log_pdf(labels))
  ```

  Args:
    matrix:  Rank `R` `Tensor`, `R >= 2`, where the last two dimensions are
      equal.
    transform:  Element-wise function mapping `Tensors` to `Tensors`.  To
      be applied to the diagonal of `matrix`.  If `None`, `matrix` is returned
      unchanged.  Defaults to `None`.
    name:  A name to give created ops.
      Defaults to "batch_matrix_diag_transform".

  Returns:
    A `Tensor` with same shape and `dtype` as `matrix`.
  """
  with ops.name_scope(name, "batch_matrix_diag_transform", [matrix]):
    matrix = ops.convert_to_tensor(matrix, name="matrix")
    if transform is None:
      return matrix
    # Replace the diag with transformed diag.
    diag = array_ops.batch_matrix_diag_part(matrix)
    transformed_diag = transform(diag)
    transformed_mat = array_ops.batch_matrix_set_diag(matrix, transformed_diag)

  return transformed_mat


def rotate_transpose(x, shift, name="rotate_transpose"):
  """Circularly moves dims left or right.

  Effectively identical to:

  ```python
  numpy.transpose(x, numpy.roll(numpy.arange(len(x.shape)), shift))
  ```

  When `validate_args=False` additional graph-runtime checks are
  performed. These checks entail moving data from to GPU to CPU.

  Example:

    ```python
    x = ... # Tensor of shape [1, 2, 3, 4].
    rotate_transpose(x, -1)  # result shape: [2, 3, 4, 1]
    rotate_transpose(x, -2)  # result shape: [3, 4, 1, 2]
    rotate_transpose(x,  1)  # result shape: [4, 1, 2, 3]
    rotate_transpose(x,  2)  # result shape: [3, 4, 1, 2]
    rotate_transpose(x, 7) == rotate_transpose(x, 3)
    rotate_transpose(x, -7) == rotate_transpose(x, -3)
    ```

  Args:
    x: `Tensor`.
    shift: `Tensor`. Number of dimensions to transpose left (shift<0) or
      transpose right (shift>0).
    name: `String`. The name to give this op.

  Returns:
    rotated_x: Input `Tensor` with dimensions circularly rotated by shift.

  Raises:
    TypeError: if shift is not integer type.
  """
  with ops.name_scope(name, values=[x, shift]):
    x = ops.convert_to_tensor(x, name="x")
    shift = ops.convert_to_tensor(shift, name="shift")
    # We do not assign back to preserve constant-ness.
    check_ops.assert_integer(shift)
    shift_value_static = tensor_util.constant_value(shift)
    ndims = x.get_shape().ndims
    if ndims is not None and shift_value_static is not None:
      if ndims < 2: return x
      shift_value_static = np.sign(shift_value_static) * (
          abs(shift_value_static) % ndims)
      if shift_value_static == 0: return x
      perm = np.roll(np.arange(ndims), shift_value_static)
      return array_ops.transpose(x, perm=perm)
    else:
      # Consider if we always had a positive shift, and some specified
      # direction.
      # When shifting left we want the new array:
      #   last(x, n-shift) + first(x, shift)
      # and if shifting right then we want:
      #   last(x, shift) + first(x, n-shift)
      # Observe that last(a) == slice(a, n) and first(a) == slice(0, a).
      # Also, we can encode direction and shift as one: direction * shift.
      # Combining these facts, we have:
      #   a = cond(shift<0, -shift, n-shift)
      #   last(x, n-a) + first(x, a) == x[a:n] + x[0:a]
      # Finally, we transform shift by modulo length so it can be specified
      # independently from the array upon which it operates (like python).
      ndims = array_ops.rank(x)
      shift = math_ops.select(math_ops.less(shift, 0),
                              math_ops.mod(-shift, ndims),
                              ndims - math_ops.mod(shift, ndims))
      first = math_ops.range(0, shift)
      last = math_ops.range(shift, ndims)
      perm = array_ops.concat(0, (last, first))
      return array_ops.transpose(x, perm=perm)


def pick_vector(cond,
                true_vector,
                false_vector,
                name="pick_vector"):
  """Picks possibly different length row `Tensor`s based on condition.

  Value `Tensor`s should have exactly one dimension.

  If `cond` is a python Boolean or `tf.constant` then either `true_vector` or
  `false_vector` is immediately returned. I.e., no graph nodes are created and
  no validation happens.

  Args:
    cond: `Tensor`. Must have `dtype=tf.bool` and be scalar.
    true_vector: `Tensor` of one dimension. Returned when cond is `True`.
    false_vector: `Tensor` of one dimension. Returned when cond is `False`.
    name: `String`. The name to give this op.

  Example:

  ```python
  pick_vector(tf.less(0, 5), tf.range(10, 12), tf.range(15, 18))
  # result is tensor: [10, 11].
  pick_vector(tf.less(5, 0), tf.range(10, 12), tf.range(15, 18))
  # result is tensor: [15, 16, 17].
  ```

  Returns:
    true_or_false_vector: `Tensor`.

  Raises:
    TypeError: if `cond.dtype != tf.bool`
    TypeError: if `cond` is not a constant and
      `true_vector.dtype != false_vector.dtype`
  """
  with ops.op_scope((cond, true_vector, false_vector), name):
    cond = ops.convert_to_tensor(cond, name="cond")
    if cond.dtype != dtypes.bool:
      raise TypeError("%s.dtype=%s which is not %s" %
                      (cond.name, cond.dtype, dtypes.bool))
    cond_value_static = tensor_util.constant_value(cond)
    if cond_value_static is not None:
      return true_vector if cond_value_static else false_vector
    true_vector = ops.convert_to_tensor(true_vector, name="true_vector")
    false_vector = ops.convert_to_tensor(false_vector, name="false_vector")
    if true_vector.dtype != false_vector.dtype:
      raise TypeError(
          "%s.dtype=%s does not match %s.dtype=%s"
          % (true_vector.name, true_vector.dtype,
             false_vector.name, false_vector.dtype))
    n = array_ops.shape(true_vector)[0]
    return array_ops.slice(array_ops.concat(0, (true_vector, false_vector)),
                           [math_ops.select(cond, 0, n)],
                           [math_ops.select(cond, n, -1)])


def append_class_fun_doc(fn, doc_str):
  """Appends the `doc_str` argument to `fn.__doc__`.

  This function is primarily needed because Python 3 changes how docstrings are
  programmatically set.

  Args:
    fn: Class function.
    doc_str: String
  """
  # TODO(b/31100586): Figure out why appending accumulates rather than resets
  # for each subclass.
  if sys.version_info.major < 3:
    if fn.__func__.__doc__ is None:
      fn.__func__.__doc__ = doc_str
    # else:
    #   fn.__func__.__doc__ += doc_str
  else:
    if fn.__doc__ is None:
      fn.__doc__ = doc_str
    # else:
    #   fn.__doc__ += doc_str
