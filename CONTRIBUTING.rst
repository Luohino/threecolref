3ColRef — Notes For Developers
=============================

3ColRef is written in Python and PyQt6.


Developing
----------

Optional step: Use pyenv to create a virtual environment::

  pyenv install -v 3.11
  pyenv virtualenv 3.11 threecolref

Once the vitrual environment is set up, you can enter it with::

  pyenv activate threecolref


Clone the repository and install threecolref and its dependencies::

  git clone https://github.com/Luohino/threecolref.git
  cd threecolref
  pip install -e .

Install additional development requirements::

  pip install -r requirements/dev.txt

Run unittests with::

  pytest --cov .

This will also generate a coverage report:  ``htmlcov/index.html``.

Run codechecks with::

  flake8 .

threecolref files are sqlite databases, so they can be inspected with any sqlite browser.

For debugging options, run::

  threecolref --help


Building the app
----------------

To build the app, run::

  pyinstaller threecolref.spec

You will find the generated executable in the folder ``dist``.


Website etc.
------------
