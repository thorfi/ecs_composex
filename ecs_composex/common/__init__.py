#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2020-2022 John Mille <john@compose-x.io>

"""
Most commonly used functions shared across all modules.
"""

import logging as logthings
import re
import sys
from copy import deepcopy
from datetime import datetime as dt
from math import ceil, log
from os import environ
from uuid import uuid4

import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

from compose_x_common.compose_x_common import keyisset, keypresent, set_else_none
from troposphere import AWS_NO_VALUE, Output
from troposphere import Parameter as CfnParameter
from troposphere import Ref, Template

from ecs_composex import __version__ as version
from ecs_composex.common import cfn_conditions
from ecs_composex.common.cfn_params import ROOT_STACK_NAME, Parameter

DATE = dt.utcnow().isoformat()
FILE_PREFIX = f'{dt.utcnow().strftime("%Y/%m/%d/%H%M")}/{str(uuid4().hex)[:6]}'
NONALPHANUM = re.compile(r"([^a-zA-Z0-9]+)")


def no_value_if_not_set(props, key, is_bool=False):
    """
    Function to simplify setting value if the key is in the dict and else Ref(AWS_NO_VALUE) for resource properties

    :param dict props:
    :param str key:
    :param bool is_bool:
    :return:
    """
    if not is_bool:
        return Ref(AWS_NO_VALUE) if not keyisset(key, props) else props[key]
    else:
        return Ref(AWS_NO_VALUE) if not keypresent(key, props) else props[key]


def init_template(description=None):
    """Function to initialize the troposphere base template

    :param description: Description used for the CFN
    :type description: str

    :returns: template
    :rtype: Template
    """
    if description is not None:
        template = Template(description)
    else:
        template = Template("Template generated by ECS ComposeX")
    template.set_metadata(
        deepcopy(
            {
                "Type": "ComposeX",
                "Properties": {"Version": version, "GeneratedOn": DATE},
            }
        )
    )
    template.set_version()
    return template


def add_parameter_to_group_label(
    interface_metadata: dict, parameter: Parameter
) -> None:
    """
    Simply goes over the ParameterGroups of the metadata.AWS::CloudFormation::Interface
    and if already exists, adds to group, else, create group and adds first element

    :param dict interface_metadata:
    :param ecs_composex.common.cfn_params.Parameter parameter:
    """
    groups = set_else_none("ParameterGroups", interface_metadata, [], eval_bool=True)
    if not groups:
        interface_metadata["ParameterGroups"] = groups
        groups.append(
            {
                "Label": {"default": parameter.group_label},
                "Parameters": [parameter.title],
            }
        )
    else:
        for group in groups:
            if group["Label"]["default"] == parameter.group_label:
                if parameter.title not in group["Parameters"]:
                    group["Parameters"].append(parameter.title)
                break
        else:
            groups.append(
                {
                    "Label": {"default": parameter.group_label},
                    "Parameters": [parameter.title],
                }
            )


def add_parameters_metadata(template, parameter):
    """
    Simple function that will auto-add  AWS::CloudFormation::Interface to the template if the parameter
    has a group and labels defined

    :param template:
    :param parameter:
    :return:
    """
    if not hasattr(template, "metadata"):
        metadata = {}
    else:
        metadata = getattr(template, "metadata")
    interface_metadata = set_else_none("AWS::CloudFormation::Interface", metadata, {})
    if not interface_metadata:
        metadata["AWS::CloudFormation::Interface"] = interface_metadata
    if parameter.group_label:
        add_parameter_to_group_label(interface_metadata, parameter)
    if parameter.label:
        labels = set_else_none(
            "ParameterLabels", interface_metadata, {}, eval_bool=True
        )
        if not labels:
            interface_metadata["ParameterLabels"] = labels
            labels[parameter.title] = {"default": parameter.label}
        else:
            labels.update({parameter.title: {"default": parameter.label}})


def add_parameters(template: Template, parameters: list) -> None:
    """Function to add parameters to the template

    :param template: the template to add the parameters to
    :type template: troposphere.Template
    :param parameters: list of parameters to add to the template
    :type parameters: list<ecs_composex.common.cfn_params.Parameter>
    """
    for param in parameters:
        if not isinstance(param, (Parameter, CfnParameter)) or not issubclass(
            type(param), (Parameter, CfnParameter)
        ):
            raise TypeError("Parameter must be of type", Parameter, "Got", type(param))
        if template and param.title not in template.parameters:
            template.add_parameter(param)
        if isinstance(param, Parameter) and (param.group_label or param.label):
            add_parameters_metadata(template, param)


def add_outputs(template, outputs):
    """Function to add parameters to the template

    :param template: the template to add the parameters to
    :type template: troposphere.Template
    :param outputs: list of parameters to add to the template
    :type outputs: list<troposphere.Output>
    """
    for output in outputs:
        if not isinstance(output, Output):
            raise TypeError("Parameter must be of type", Output)
        if template and output.title not in template.outputs:
            template.add_output(output)


def add_update_mapping(template, mapping_key, mapping_value, mapping_subkey=None):
    """

    :param troposphere.Template template:
    :param str mapping_key:
    :param dict mapping_value:
    :param str mapping_subkey: If set, applies the value to a sub-key of the mapping on update
    :return:
    """
    if mapping_key not in template.mappings:
        template.add_mapping(mapping_key, mapping_value)
    else:
        if mapping_subkey and keyisset(mapping_subkey, template.mappings[mapping_key]):
            template.mappings[mapping_key][mapping_subkey].update(mapping_value)
        elif (
            mapping_key
            and mapping_subkey
            and not keyisset(mapping_subkey, template.mappings[mapping_key])
        ):
            template.mappings[mapping_key][mapping_subkey] = mapping_value
        elif not mapping_subkey:
            template.mappings[mapping_key].update(mapping_value)


def add_resource(template, resource, replace=False):
    """
    Function to add resource to template if the resource does not already exist

    :param troposphere.Template template:
    :param troposphere.AWSObject resource:
    :param bool replace:
    """
    if resource not in template.resources.values():
        template.add_resource(resource)
    elif resource in template.resources.values() and replace:
        template.resources[resource.title] = resource


def add_defaults(template):
    """Function to CFN parameters and conditions to the template whhich are used
    across ECS ComposeX

    :param template: source template to add the params and conditions to
    :type template: Template
    """
    template.add_parameter(ROOT_STACK_NAME)
    template.add_condition(
        cfn_conditions.USE_STACK_NAME_CON_T, cfn_conditions.USE_STACK_NAME_CON
    )


def build_template(description=None, *parameters):
    """
    Entry point function to creating the template for ECS ComposeX resources

    :param description: Optional custom description for the CFN template
    :type description: str, optional
    :param parameters: List of optional parameters to add to the template.
    :type parameters: List<troposphere.Parameters>, optional

    :returns template: the troposphere template
    :rtype: Template
    """
    template = init_template(description)
    if parameters:
        add_parameters(template, *parameters)
    add_defaults(template)
    return template


def validate_resource_title(resource_name, resource_type=None):
    """Function to validate the key for the resource is valid

    :param resource_name: Name of the resource to evaluate
    :type resource_name: str
    :param resource_type: category of the resource, optional
    :type resource_type: str

    :returns: True/False
    :rtype: bool
    """
    if NONALPHANUM.findall(resource_name):
        raise ValueError(
            f"The resource {resource_name} in {resource_type} "
            "section contains non alphanumerical characters",
            NONALPHANUM.findall(resource_name),
        )
    return True


def validate_input(compose_content, res_key):
    """Function to validate the resources names in ComposeX File
    for a given resource key

    :param compose_content: the docker/ComposeX content
    :type compose_content: dict
    :param res_key: key of the category in docker compose to look for
    :type res_key: str

    :return: True/False if all keys are valid
    :rtype: bool
    """
    section = compose_content[res_key]
    for resource_name in section.keys():
        validate_resource_title(resource_name, res_key)
    return True


def validate_kwargs(required_keys, kwargs, caller=None):
    """Function to ensure minimum keys in kwargs are present.

    :param required_keys: the list of keys that have to be present
    :type required_keys: list
    :param kwargs: the arguments to verify
    :type kwargs: dict or set
    :param caller: optional argument to help understand what's missing
    :type caller: str

    :return: True/False if all keys are valid
    :rtype: bool

    :raises: KeyError if key is missing from kwargs
    """
    for required_key in required_keys:
        if not keyisset(required_key, kwargs):
            raise KeyError(required_key, "is required by module", caller)
    return True


def setup_logging():
    """Function to setup logging for ECS ComposeX.
    In case this is used in a Lambda function, removes the AWS Lambda default log handler

    :returns: the_logger
    :rtype: Logger
    """
    level = environ.get("LOGLEVEL")
    default_level = True
    formats = {
        "INFO": logthings.Formatter(
            "%(asctime)s [%(levelname)8s] %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ),
        "DEBUG": logthings.Formatter(
            "%(asctime)s [%(levelname)8s] %(filename)s.%(lineno)d , %(funcName)s, %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ),
    }

    if level is not None and isinstance(level, str):
        logthings.basicConfig(level=level.upper())
        default_level = False
    else:
        logthings.basicConfig(level="INFO")

    root_logger = logthings.getLogger()
    for h in root_logger.handlers:
        root_logger.removeHandler(h)
    the_logger = logthings.getLogger("EcsComposeX")

    if not the_logger.handlers:
        if default_level:
            formatter = formats["INFO"]
        elif keyisset(level.upper(), formats):
            formatter = formats[level.upper()]
        else:
            formatter = formats["DEBUG"]
        handler = logthings.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        the_logger.addHandler(handler)

    return the_logger


def build_parameters_file(params, parameter_name, parameter_value):
    """
    Function to build arguments file to pass onto CFN.
    Adds the parameter key/value so it can be written to file afterwards

    :param params: list of parameters
    :type params: list
    :param parameter_name: key of the parameter
    :type parameter_name: str
    :param parameter_value: value of the parameter
    :type parameter_value: str||list
    """
    if params is None:
        params = []
    if isinstance(parameter_value, (int, float)):
        parameter_value = str(parameter_value)
    params.append({"ParameterKey": parameter_name, "ParameterValue": parameter_value})


def load_composex_file(file_path):
    """
    File to load and read the docker compose file

    :param file_path: path to the docker compose file
    :type file_path: str

    :return: content of the docker file
    :rtype: dict
    """
    with open(file_path, "r") as composex_fd:
        return yaml.load(composex_fd.read(), Loader=Loader)


def clpow2(x):
    """
    Function to return the closest power of two from given x

    :param x: Number to look the closest power of two for

    :returns: int() closest power of two
    """
    return pow(2, int(log(x, 2) + 0.5))


def nxtpow2(x):
    """Function to find the next power of two from given x number

    :param x: number to look for the next power of two

    :returns: next power of two number
    """
    return int(pow(2, ceil(log(x, 2))))


LOG = setup_logging()
