#!/usr/bin/env python

# Copyright 2017 The Kubernetes Authors.
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

"""Create e2e test definitions.

Usage example:

  In $GOPATH/src/k8s.io/test-infra,

  $ bazel run //experiment:generate_tests -- \
      --yaml-config-path=experiment/test_config.yaml \
"""

import argparse
import hashlib
import os
import ruamel.yaml as yaml


# TODO(yguo0905): Generate Prow and testgrid configurations.

PROW_CONFIG_TEMPLATE = """
    tags:
    - generated # AUTO-GENERATED by experiment/generate_tests.py - DO NOT EDIT!
    interval:
    cron:
    labels:
      preset-service-account: "true"
      preset-k8s-ssh: "true"
    name:
    spec:
      containers:
      - args:
        env:
        image: gcr.io/k8s-testimages/kubekins-e2e:v20190730-dbac84b-master
"""


E2E_TESTGRID_CONFIG_TEMPLATE = """
  name: 
  gcs_prefix: 
  column_header:
    - configuration_value: node_os_image
    - configuration_value: master_os_image
    - configuration_value: Commit
    - configuration_value: infra-commit
"""

GCS_LOG_PREFIX = "kubernetes-jenkins/logs/"

COMMENT = 'AUTO-GENERATED by experiment/generate_tests.py - DO NOT EDIT.'

TESTGRID_CONFIG_PREAMBLE = COMMENT + """

default_test_group:
  days_of_results: 14 # Number of days of test results to gather and serve.
  tests_name_policy: 2 # replace the name of the test
  ignore_pending: false # Show in-progress tests.
  column_header:
    - configuration_value: Commit # Shows the commit number on column header
    - configuration_value: infra-commit
  num_columns_recent: 10
  use_kubernetes_client: true # These two fields are deprecated and should always be true
  is_external: true
  alert_stale_results_hours: 0 # Don't alert for staleness by default.
  num_failures_to_alert: 3 # Consider a test failed if it has 3 or more consecutive failures.
  num_passes_to_disable_alert: 1 # A failing test passes if it has 1 or more consecutive passes.
  code_search_path: github.com/kubernetes/kubernetes/search # URL for regression search links.

default_dashboard_tab:
  open_test_template: # The URL template to visit after clicking on a cell
    url: https://prow.k8s.io/view/gcs/<gcs_prefix>/<changelist>
  file_bug_template: # The URL template to visit when filing a bug
    url: https://github.com/kubernetes/kubernetes/issues/new
    options:
      - key: title
        value: 'E2E: <test-name>'
      - key: body
        value: <test-url>
  attach_bug_template: # The URL template to visit when attaching a bug
    url: # empty
    options: #empty
  results_text: See these results on Prow # Shown in the about menu as a link to view the results
  results_url_template: # The URL template to visit after clicking
    url: https://prow.k8s.io/job-history/<gcs_prefix>
  code_search_path: github.com/kubernetes/kubernetes/search # URL for regression search links.
  num_columns_recent: 10
  code_search_url_template: # The URL template to visit when searching for changelists
    url: https://github.com/kubernetes/kubernetes/compare/<start-custom-0>...<end-custom-0>
"""


def get_sha1_hash(data):
    """Returns the SHA1 hash of the specified data."""
    sha1_hash = hashlib.sha1()
    sha1_hash.update(data)
    return sha1_hash.hexdigest()


def substitute(job_name, lines):
    """Replace '${job_name_hash}' in lines with the SHA1 hash of job_name."""
    return [line.replace('${job_name_hash}', get_sha1_hash(job_name)[:10]) \
            for line in lines]

def get_args(job_name, field):
    """Returns a list of args for the given field."""
    if not field:
        return []
    return substitute(job_name, field.get('args', []))


def write_prow_configs_file(output_file, job_defs):
    """Writes the Prow configurations into output_file."""
    with open(output_file, 'w') as fp:
        yaml.dump(
            job_defs, fp, Dumper=yaml.RoundTripDumper, width=float("inf"))

def write_testgrid_config_file(output_file, testgrid_config):
    """Writes the TestGrid test group configurations into output_file."""
    with open(output_file, 'w') as fp:
        fp.write('# ' + TESTGRID_CONFIG_PREAMBLE + '\n\n')
        yaml.dump(
            testgrid_config, fp, Dumper=yaml.RoundTripDumper, width=float("inf"))

def apply_job_overrides(envs_or_args, job_envs_or_args):
    '''Applies the envs or args overrides defined in the job level'''
    for job_env_or_arg in job_envs_or_args:
        name = job_env_or_arg.split('=', 1)[0]
        env_or_arg = next(
            (x for x in envs_or_args if (x.strip().startswith('%s=' % name) or
                                         x.strip() == name)), None)
        if env_or_arg:
            envs_or_args.remove(env_or_arg)
        envs_or_args.append(job_env_or_arg)


class E2ENodeTest(object):

    def __init__(self, job_name, job, config):
        self.job_name = job_name
        self.job = job
        self.common = config['nodeCommon']
        self.images = config['nodeImages']
        self.k8s_versions = config['nodeK8sVersions']
        self.test_suites = config['nodeTestSuites']

    def __get_job_def(self, args):
        """Returns the job definition from the given args."""
        return {
            'scenario': 'kubernetes_e2e',
            'args': args,
            'sigOwners': self.job.get('sigOwners') or ['UNNOWN'],
            # Indicates that this job definition is auto-generated.
            'tags': ['generated'],
            '_comment': COMMENT,
        }

    def __get_prow_config(self, test_suite, k8s_version):
        """Returns the Prow config for the job from the given fields."""
        prow_config = yaml.round_trip_load(PROW_CONFIG_TEMPLATE)
        prow_config['name'] = self.job_name
        if 'interval' in self.job:
            del prow_config['cron']
            prow_config['interval'] = self.job['interval']
        elif 'cron' in self.job:
            del prow_config['cron']
            prow_config['cron'] = self.job['cron']
        else:
            raise Exception("no interval or cron definition found")
        # Assumes that the value in --timeout is of minutes.
        timeout = int(next(
            x[10:-1] for x in test_suite['args'] if (
                x.startswith('--timeout='))))
        container = prow_config['spec']['containers'][0]
        if not container['args']:
            container['args'] = []
        if not container['env']:
            container['env'] = []
        # Prow timeout = job timeout + 20min
        container['args'].append('--timeout=%d' % (timeout + 20))
        container['args'].extend(k8s_version.get('args', []))
        container['args'].append('--root=/go/src')
        container['env'].extend([{'name':'GOPATH', 'value': '/go'}])
        # Specify the appropriate kubekins-e2e image. This allows us to use a
        # specific image (containing a particular Go version) to build and
        # trigger the node e2e test to avoid issues like
        # https://github.com/kubernetes/kubernetes/issues/43534.
        if k8s_version.get('prowImage', None):
            container['image'] = k8s_version['prowImage']
        return prow_config

    def generate(self):
        '''Returns the job and the Prow configurations for this test.'''
        fields = self.job_name.split('-')
        if len(fields) != 6:
            raise ValueError('Expected 6 fields in job name', self.job_name)

        image = self.images[fields[3]]
        k8s_version = self.k8s_versions[fields[4][3:]]
        test_suite = self.test_suites[fields[5]]

        # envs are disallowed in node e2e tests.
        if 'envs' in self.common or 'envs' in image or 'envs' in test_suite:
            raise ValueError(
                'envs are disallowed in node e2e test', self.job_name)
        # Generates args.
        args = []
        args.extend(get_args(self.job_name, self.common))
        args.extend(get_args(self.job_name, image))
        args.extend(get_args(self.job_name, test_suite))
        # Generates job config.
        job_config = self.__get_job_def(args)
        # Generates prow config.
        prow_config = self.__get_prow_config(test_suite, k8s_version)

        # Combine --node-args
        node_args = []
        job_args = []
        for arg in job_config['args']:
            if '--node-args=' in arg:
                node_args.append(arg.split('=', 1)[1])
            else:
                job_args.append(arg)

        if node_args:
            flag = '--node-args='
            for node_arg in node_args:
                flag += '%s ' % node_arg
            job_args.append(flag.strip())

        job_config['args'] = job_args

        if image.get('testgrid_prefix') is not None:
            dashboard = '%s-%s-%s' % (image['testgrid_prefix'], fields[3],
                                      fields[4])
            annotations = prow_config.setdefault('annotations', {})
            annotations['testgrid-dashboards'] = dashboard
            tab_name = '%s-%s-%s' % (fields[3], fields[4], fields[5])
            annotations['testgrid-tab-name'] = tab_name

        return job_config, prow_config, None


class E2ETest(object):

    def __init__(self, output_dir, job_name, job, config):
        self.env_filename = os.path.join(output_dir, '%s.env' % job_name),
        self.job_name = job_name
        self.job = job
        self.common = config['common']
        self.cloud_providers = config['cloudProviders']
        self.images = config['images']
        self.k8s_versions = config['k8sVersions']
        self.test_suites = config['testSuites']

    def __get_job_def(self, args):
        """Returns the job definition from the given args."""
        return {
            'scenario': 'kubernetes_e2e',
            'args': args,
            'sigOwners': self.job.get('sigOwners') or ['UNNOWN'],
            # Indicates that this job definition is auto-generated.
            'tags': ['generated'],
            '_comment': COMMENT,
        }

    def __get_prow_config(self, test_suite):
        """Returns the Prow config for the e2e job from the given fields."""
        prow_config = yaml.round_trip_load(PROW_CONFIG_TEMPLATE)
        prow_config['name'] = self.job_name
        if 'interval' in self.job:
            del prow_config['cron']
            prow_config['interval'] = self.job['interval']
        elif 'cron' in self.job:
            del prow_config['interval']
            prow_config['cron'] = self.job['cron']
        else:
            raise Exception("no interval or cron definition found")
        # Assumes that the value in --timeout is of minutes.
        timeout = int(next(
            x[10:-1] for x in test_suite['args'] if (
                x.startswith('--timeout='))))
        container = prow_config['spec']['containers'][0]
        if not container['args']:
            container['args'] = []
        container['args'].append('--bare')
        # Prow timeout = job timeout + 20min
        container['args'].append('--timeout=%d' % (timeout + 20))
        return prow_config

    def __get_testgrid_config(self):
        tg_config = yaml.round_trip_load(E2E_TESTGRID_CONFIG_TEMPLATE)
        tg_config['name'] = self.job_name
        tg_config['gcs_prefix'] = GCS_LOG_PREFIX + self.job_name
        return tg_config

    def initialize_dashboards_with_release_blocking_info(self, version):
        dashboards = []
        if self.job.get('releaseBlocking'):
            dashboards.append('sig-release-%s-blocking' % version)
        else:
            dashboards.append('sig-release-%s-all' % version)
        return dashboards

    def generate(self):
        '''Returns the job and the Prow configurations for this test.'''
        fields = self.job_name.split('-')
        if len(fields) != 7:
            raise ValueError('Expected 7 fields in job name', self.job_name)

        cloud_provider = self.cloud_providers[fields[3]]
        image = self.images[fields[4]]
        k8s_version = self.k8s_versions[fields[5][3:]]
        test_suite = self.test_suites[fields[6]]

        # Generates args.
        args = []
        args.extend(get_args(self.job_name, self.common))
        args.extend(get_args(self.job_name, cloud_provider))
        args.extend(get_args(self.job_name, image))
        args.extend(get_args(self.job_name, k8s_version))
        args.extend(get_args(self.job_name, test_suite))
        # Generates job config.
        job_config = self.__get_job_def(args)
        # Generates Prow config.
        prow_config = self.__get_prow_config(test_suite)

        tg_config = self.__get_testgrid_config()

        annotations = prow_config.setdefault('annotations', {})
        tab_name = '%s-%s-%s-%s' % (fields[3], fields[4], fields[5], fields[6])
        annotations['testgrid-tab-name'] = tab_name
        dashboards = self.initialize_dashboards_with_release_blocking_info(k8s_version['version'])
        if image.get('testgrid_prefix') is not None:
            dashboard = '%s-%s-%s' % (image['testgrid_prefix'], fields[4],
                                      fields[5])
            dashboards.append(dashboard)
        annotations['testgrid-dashboards'] = ', '.join(dashboards)

        return job_config, prow_config, tg_config


def for_each_job(output_dir, job_name, job, yaml_config):
    """Returns the job config and the Prow config for one test job."""
    fields = job_name.split('-')
    if len(fields) < 3:
        raise ValueError('Expected at least 3 fields in job name', job_name)
    job_type = fields[2]

    # Generates configurations.
    if job_type == 'e2e':
        generator = E2ETest(output_dir, job_name, job, yaml_config)
    elif job_type == 'e2enode':
        generator = E2ENodeTest(job_name, job, yaml_config)
    else:
        raise ValueError('Unexpected job type ', job_type)
    job_config, prow_config, testgrid_config = generator.generate()

    # Applies job-level overrides.
    apply_job_overrides(job_config['args'], get_args(job_name, job))

    # merge job_config into prow_config
    args = prow_config['spec']['containers'][0]['args']
    args.append('--scenario=' + job_config['scenario'])
    args.append('--')
    args.extend(job_config['args'])

    return prow_config, testgrid_config


def main(yaml_config_path, output_dir, testgrid_output_path):
    """Creates test job definitions.

    Converts the test configurations in yaml_config_path to the job definitions
    in output_dir/generated.yaml.
    """
    # TODO(yguo0905): Validate the configurations from yaml_config_path.

    with open(yaml_config_path) as fp:
        yaml_config = yaml.safe_load(fp)

    output_config = {}
    output_config['periodics'] = []
    testgrid_config = {'test_groups': []}
    for job_name, _ in yaml_config['jobs'].items():
        # Get the envs and args for each job defined under "jobs".
        prow, testgrid = for_each_job(
            output_dir, job_name, yaml_config['jobs'][job_name], yaml_config)
        output_config['periodics'].append(prow)
        if testgrid is not None:
            testgrid_config['test_groups'].append(testgrid)

    # Write the job definitions to --output-dir/generated.yaml
    write_prow_configs_file(output_dir + 'generated.yaml', output_config)
    write_testgrid_config_file(testgrid_output_path, testgrid_config)


if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(
        description='Create test definitions from the given yaml config')
    PARSER.add_argument('--yaml-config-path', help='Path to config.yaml')
    PARSER.add_argument(
        '--output-dir',
        help='Prowjob config output dir',
        default='config/jobs/kubernetes/generated/')
    PARSER.add_argument(
        '--testgrid-output-path',
        help='Path to testgrid output file',
        default='config/testgrids/generated-test-config.yaml')
    ARGS = PARSER.parse_args()

    main(
        ARGS.yaml_config_path,
        ARGS.output_dir,
        ARGS.testgrid_output_path)
