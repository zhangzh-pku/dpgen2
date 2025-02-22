import json
import os
import pickle
import shutil
import time
import unittest
from pathlib import Path
from typing import List, Set

import jsonpickle
import numpy as np
from dflow import (InputArtifact, Inputs, OutputArtifact, OutputParameter,
                   Outputs, S3Artifact, Step, Steps, Workflow,
                   download_artifact, upload_artifact)
from dflow.python import OP, OPIO, Artifact, OPIOSign, PythonOPTemplate

try:
    from context import dpgen2
except ModuleNotFoundError:
    # case of upload everything to argo, no context needed
    pass
from dpgen2.constants import (lmp_conf_name, lmp_input_name, lmp_log_name,
                              lmp_model_devi_name, lmp_task_pattern,
                              lmp_traj_name, model_name_pattern,
                              train_log_name, train_script_name,
                              train_task_pattern)
from dpgen2.exploration.task import ExplorationTask, ExplorationTaskGroup
from dpgen2.op.prep_lmp import PrepLmp
from dpgen2.superop.prep_run_lmp import PrepRunLmp
from dpgen2.utils.step_config import normalize as normalize_step_dict

from context import (default_host, default_image, skip_ut_with_dflow,
                     skip_ut_with_dflow_reason, upload_python_package)
from mocked_ops import MockedRunLmp, mocked_numb_models

default_config = normalize_step_dict(
    {"template_config": {
        "image": default_image,
    }})


def make_task_group_list(ngrp, ntask_per_grp):
    tgrp = ExplorationTaskGroup()
    for ii in range(ngrp):
        for jj in range(ntask_per_grp):
            tt = ExplorationTask()
            tt\
                .add_file(lmp_conf_name, f'group{ii} task{jj} conf')\
                .add_file(lmp_input_name, f'group{ii} task{jj} input')
            tgrp.add_task(tt)
    return tgrp


def check_lmp_tasks(tcase, ngrp, ntask_per_grp):
    cc = 0
    tdirs = []
    for ii in range(ngrp):
        for jj in range(ntask_per_grp):
            tdir = lmp_task_pattern % cc
            tdirs.append(tdir)
            tcase.assertTrue(Path(tdir).is_dir())
            fconf = Path(tdir) / lmp_conf_name
            finpt = Path(tdir) / lmp_input_name
            tcase.assertTrue(fconf.is_file())
            tcase.assertTrue(finpt.is_file())
            tcase.assertEqual(fconf.read_text(), f'group{ii} task{jj} conf')
            tcase.assertEqual(finpt.read_text(), f'group{ii} task{jj} input')
            cc += 1
    return tdirs


@unittest.skipIf(skip_ut_with_dflow, skip_ut_with_dflow_reason)
class TestPrepRunLmp(unittest.TestCase):

    def setUp(self):
        self.ngrp = 2
        self.ntask_per_grp = 3
        self.task_group_list = make_task_group_list(self.ngrp,
                                                    self.ntask_per_grp)
        self.nmodels = mocked_numb_models
        self.model_list = []
        for ii in range(self.nmodels):
            model = Path(f'model{ii}.pb')
            model.write_text(f'model {ii}')
            self.model_list.append(model)
        self.models = upload_artifact(self.model_list)

    def tearDown(self):
        for ii in range(self.nmodels):
            model = Path(f'model{ii}.pb')
            if model.is_file():
                os.remove(model)
        for ii in range(self.ngrp * self.ntask_per_grp):
            work_path = Path(f'task.{ii:06d}')
            if work_path.is_dir():
                shutil.rmtree(work_path)

    def check_run_lmp_output(
        self,
        task_name: str,
        models: List[Path],
    ):
        cwd = os.getcwd()
        os.chdir(task_name)
        fc = []
        idx = int(task_name.split('.')[-1])
        ii = idx // self.ntask_per_grp
        jj = idx - ii * self.ntask_per_grp
        fc.append(f'group{ii} task{jj} conf')
        fc.append(f'group{ii} task{jj} input')
        for ii in [ii.name for ii in models]:
            fc.append((Path(cwd) / ii).read_text())

        os.chdir(cwd)
        log_path = Path(task_name) / "../../log/" / task_name.split(
            '/')[-1] / lmp_log_name
        self.assertEqual(fc, log_path.read_text().strip().split("\n"))
        traj_path = Path(task_name) / "../../traj/" / task_name.split(
            '/')[-1] / lmp_traj_name
        name = task_name.split('/')[-1]
        self.assertEqual(f'traj of {name}',
                         traj_path.read_text().split('\n')[0])
        model_devi_path = Path(
            task_name) / "../../model_devi" / task_name.split(
                '/')[-1] / lmp_model_devi_name
        self.assertEqual(f'model_devi of {name}',
                         Path(model_devi_path).read_text())

        os.chdir(cwd)

    def test(self):
        steps = PrepRunLmp(
            "prep-run-lmp",
            PrepLmp,
            MockedRunLmp,
            upload_python_package=upload_python_package,
            prep_config=default_config,
            run_config=default_config,
        )
        prep_run_step = Step(
            'prep-run-step',
            template=steps,
            parameters={
                "lmp_config": {},
                "lmp_task_grp": self.task_group_list,
            },
            artifacts={
                "models": self.models,
            },
        )

        wf = Workflow(name="dp-train", host=default_host)
        wf.add(prep_run_step)
        wf.submit()
        if config["mode"] == "debug":
            step = prep_run_step
        else:
            while wf.query_status() in ["Pending", "Running"]:
                time.sleep(4)

            self.assertEqual(wf.query_status(), "Succeeded")
            step = wf.query_step(name="prep-run-step")[0]
        self.assertEqual(step.phase, "Succeeded")

        download_artifact(step.outputs.artifacts["model_devis"])
        download_artifact(step.outputs.artifacts["trajs"])
        download_artifact(step.outputs.artifacts["logs"])

        for ii in step.outputs.parameters['task_names'].value:
            path = wf.id + '/--run-lmp-group/model_devi/' + ii
            if config["mode"] == "debug":
                self.check_run_lmp_output(path, self.model_list)
            else:
                self.check_run_lmp_output(ii, self.model_list)


if __name__ == "__main__":
    from dflow import config
    config["mode"] = "debug"
    unittest.main()
