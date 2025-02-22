import os
import numpy as np
import unittest

from dflow import (InputParameter, OutputParameter, Inputs, InputArtifact,
                   Outputs, OutputArtifact, Workflow, Step, Steps,
                   upload_artifact, download_artifact, S3Artifact, argo_range)
from dflow.python import (
    PythonOPTemplate,
    OP,
    OPIO,
    OPIOSign,
    Artifact,
)

import time, shutil, json, jsonpickle
from typing import Set, List
from pathlib import Path
try:
    from context import dpgen2
except ModuleNotFoundError:
    # case of upload everything to argo, no context needed
    pass
from context import (
    upload_python_package,
    skip_ut_with_dflow,
    skip_ut_with_dflow_reason,
    default_image,
    default_host,
)
from dpgen2.superop.prep_run_fp import PrepRunFp
from mocked_ops import (
    mocked_incar_template,
    MockedPrepVasp,
    MockedRunVasp,
)
from dpgen2.fp.vasp import VaspInputs
from dpgen2.constants import (
    vasp_task_pattern,
    vasp_conf_name,
    vasp_input_name,
    vasp_pot_name,
)
from dpgen2.utils.step_config import normalize as normalize_step_dict

default_config = normalize_step_dict(
    {"template_config": {
        "image": default_image,
    }})


def check_vasp_tasks(tcase, ntasks):
    cc = 0
    tdirs = []
    for ii in range(ntasks):
        tdir = vasp_task_pattern % cc
        tdirs.append(tdir)
        tcase.assertTrue(Path(tdir).is_dir())
        fconf = Path(tdir) / vasp_conf_name
        finpt = Path(tdir) / vasp_input_name
        tcase.assertTrue(fconf.is_file())
        tcase.assertTrue(finpt.is_file())
        tcase.assertEqual(fconf.read_text(), f'conf {ii}')
        tcase.assertEqual(finpt.read_text(), mocked_incar_template)
        cc += 1
    return tdirs


@unittest.skipIf(skip_ut_with_dflow, skip_ut_with_dflow_reason)
class TestPrepRunVasp(unittest.TestCase):

    def setUp(self):
        self.ntasks = 6
        self.confs = []
        for ii in range(self.ntasks):
            fname = Path(f'conf.{ii}')
            fname.write_text(f'conf {ii}')
            self.confs.append(fname)
        self.confs = upload_artifact(self.confs)
        self.incar = Path('incar')
        self.incar.write_text(mocked_incar_template)
        self.potcar = Path('potcar')
        self.potcar.write_text('bar')
        self.inputs_fname = Path('inputs.dat')
        self.type_map = ['H', 'O']

    def tearDown(self):
        for ii in range(self.ntasks):
            work_path = Path(vasp_task_pattern % ii)
            if work_path.is_dir():
                shutil.rmtree(work_path)
            fname = Path(f'conf.{ii}')
            os.remove(fname)
        for ii in [self.incar, self.potcar, self.inputs_fname]:
            if ii.is_file():
                os.remove(ii)

    def check_run_vasp_output(
        self,
        task_name: str,
    ):
        cwd = os.getcwd()
        os.chdir(task_name)
        fc = []
        ii = int(task_name.split('.')[-1])
        fc.append(f'conf {ii}')
        fc.append(f'incar template')
        from dflow import config
        if config["mode"] == "debug":
            pos = task_name.find("labeled_data")
            name = task_name.split('/')[-1]
            path = task_name[:pos] + 'log/' + name + '/log'
            self.assertEqual(fc, Path(path).read_text().strip().split('\n'))
        else:
            self.assertEqual(fc, Path('log').read_text().strip().split('\n'))
        if config["mode"] == "debug":
            name = task_name.split('/')[-1]
            self.assertEqual(f'labeled_data of {name}\nconf {ii}',
                             (Path(task_name) / ('data_' + name) /
                              'data').read_text())
        else:
            self.assertEqual(f'labeled_data of {task_name}\nconf {ii}',
                             (Path('data_' + task_name) / 'data').read_text())
        # self.assertEqual(f'labeled_data of {task_name}', Path('labeled_data').read_text())
        os.chdir(cwd)

    def test(self):
        steps = PrepRunFp(
            "prep-run-vasp",
            MockedPrepVasp,
            MockedRunVasp,
            upload_python_package=upload_python_package,
            prep_config=default_config,
            run_config=default_config,
        )
        vasp_inputs = VaspInputs(0.16, True, self.incar, {'foo': self.potcar})
        prep_run_step = Step(
            'prep-run-step',
            template=steps,
            parameters={
                "fp_config": {},
                'type_map': self.type_map,
                'inputs': vasp_inputs,
            },
            artifacts={
                "confs": self.confs,
            },
        )

        wf = Workflow(name="dp-train", host=default_host)
        wf.add(prep_run_step)
        wf.submit()
        from dflow import config
        if config["mode"] == "debug":
            step = prep_run_step
        else:
            while wf.query_status() in ["Pending", "Running"]:
                time.sleep(4)

            self.assertEqual(wf.query_status(), "Succeeded")
            step = wf.query_step(name="prep-run-step")[0]
        self.assertEqual(step.phase, "Succeeded")

        download_artifact(step.outputs.artifacts["labeled_data"])
        download_artifact(step.outputs.artifacts["logs"])

        for ii in step.outputs.parameters['task_names'].value:
            _path = step.outputs.artifacts["labeled_data"].local_path + '/' + ii
            self.check_run_vasp_output(_path)

        # for ii in range(6):
        #     self.check_run_vasp_output(f'task.{ii:06d}')


if __name__ == "__main__":
    from dflow import config
    config["mode"] = "debug"
    unittest.main()
