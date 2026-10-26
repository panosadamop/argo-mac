"""Replay actions use scratch storage and fake app workers, never paid calls or personal apps."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argo
from tests import scratch_dir


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.root=scratch_dir(self)
        for p in [patch.object(argo,'SKILLS',str(self.root/'skills.json')),
                  patch.object(argo,'RECENT',str(self.root/'recent.jsonl')),
                  patch.object(argo,'WORKED',str(self.root/'worked.json')),patch.object(argo,'ME_FILE',str(self.root/'me.json')),
                  patch.dict(os.environ,{'ARGO_ASK':str(self.root),'ARGO_FRONT':'Other Fixture','ARGO_FOCUS_GUARD':'1'},clear=True)]:
            p.start();self.addCleanup(p.stop)
        self.commands=['open -a Fixture','peekaboo menu click --app "com.argo.fixture" --path "Fixture > Start meeting" --no-remote',
                       'osascript -e \'tell application "System Events" to get name of every window of process "Fixture"\'']

    def test_legacy_three_steps_upgrade_and_replay_native_actions_without_ai_or_reads(self):
        (self.root/'skills.json').write_text(json.dumps({'make a fixture meeting':{'cmds':self.commands,'reply':'Started.','mine':True}}))
        with patch.object(argo,'show',return_value='opened Fixture in the background') as show,patch.object(argo,'hands',return_value=('Clicked',True)) as hands,patch.object(argo.subprocess,'run') as shell,patch.object(argo,'start_claude') as ai:
            self.assertEqual(argo.fast('Please start a new fixture meeting'),'Started.')
        show.assert_called_once_with('Fixture',True);hands.assert_called_once_with('menu','com.argo.fixture','Fixture > Start meeting')
        shell.assert_not_called();ai.assert_not_called();self.assertEqual(len(argo.skills()['make a fixture meeting']['cmds']),2)

    def test_internal_partial_request_keys_are_pruned_when_skills_load(self):
        command = argo.SHOW + ' Fixture'
        junk = 'open fixture\nAlready completed: first step\nRemaining words: second step'
        (self.root / 'skills.json').write_text(json.dumps({
            'open fixture': {'cmds': [command], 'reply': 'Opened.', 'mine': True},
            junk: {'cmds': [command], 'reply': 'Opened.', 'mine': True},
        }))
        self.assertEqual(set(argo.skills()), {'open fixture'})
        self.assertEqual(set(json.loads((self.root / 'skills.json').read_text())), {'open fixture'})

    def test_new_shortcuts_drop_reads_and_keep_the_target_when_front_app_changes(self):
        with patch.object(argo,'cached_hands',return_value=None): self.assertTrue(argo.learn('make a fixture meeting',self.commands,'Started.'))
        commands=argo.skills()['make a fixture meeting']['cmds']
        self.assertEqual(commands,[argo.SHOW+' --bg Fixture',argo.HANDS+" menu com.argo.fixture 'Fixture > Start meeting'"])
        self.assertNotIn('Other Fixture',' '.join(commands))
        self.assertIsNone(argo.shortcut_commands('export',['%s click "File > Export"'%argo.HANDS]))

    def test_a_generalized_replay_learns_the_app_it_actually_used(self):
        argo.save_skills({'put fixture alpha left':{'cmds':['open -a "Fixture Alpha"'],'reply':'Done.','mine':True}})
        resolve=lambda name:{'fixture alpha':'Fixture Alpha','fixture beta':'Fixture Beta'}.get(name.lower())
        with patch.object(argo,'app_named',side_effect=resolve),patch.object(argo,'show',return_value='opened'),patch.object(argo,'tip'):
            self.assertEqual(argo.fast('when I say layout mode, put fixture beta left'),'Done.')
        command=argo.skills()['layout mode']['cmds'][0]
        self.assertIn('Fixture Beta',command);self.assertNotIn('Fixture Alpha',command)

    def test_explicit_open_remains_foreground_and_mutating_scripts_are_kept(self):
        script='osascript -e \'tell application "Fixture" to set name of window 1 to "Done"\''
        self.assertEqual(argo.shortcut_commands('open Fixture',['open -a Fixture',script]),['open -a Fixture',script])
        self.assertEqual(argo.shortcut_commands('check',['osascript -e \'get "click"\'']),[])
        found=f'{argo.SHOW} --bg "/tmp/Guide.pdf" && ls /tmp'   # a file found by searching: only the open is replayed
        self.assertEqual(argo.shortcut_commands('study guide',['mdfind -name guide 2>/dev/null | head -20; mdfind x | grep -i y',found]),[f'{argo.SHOW} --bg /tmp/Guide.pdf'])
        with patch.object(argo,'cached_hands',return_value=None): self.assertIsNone(argo.learn('study guide',['ls /tmp > /tmp/out',found],'Opened.'))   # a write is not a lookup

    def test_act_then_sleep_then_state_read_learns_the_act_alone(self):
        play,state='osascript -e \'tell application "Fixture" to play\'','osascript -e \'tell application "Fixture" to player state as string\''
        track='osascript -e \'tell application "Fixture" to name of current track\''
        with patch.object(argo,'cached_hands',return_value=None):
            self.assertTrue(argo.learn('unpause fixture',[f'{play} && sleep 1 && {state}'],'Playing again.'))
            self.assertEqual(argo.skills()['unpause fixture']['cmds'],[play])
            self.assertEqual(argo.shortcut_commands('pause fixture',[f'{play.replace("play","pause")} && {track}']),[play.replace('play','pause')])
            self.assertIsNone(argo.shortcut_commands('play fixture',[f'{state} && {play}']))   # a read before the act: replay would act blind
            self.assertIsNone(argo.learn('play fixture',[f'{state} && sleep 1 && {play}'],'Playing.'))
            delete='osascript -e \'tell application "System Events" to tell process "Fixture" to click button "Delete" of window 1\''
            self.assertIsNone(argo.learn('clear fixture',[f'{delete} && sleep 1 && {state}'],'Cleared.'))   # risky acts stay unlearned
        self.assertEqual(set(argo.skills()),{'unpause fixture'})
        both='osascript -e \'tell application "Fixture" to pause\' -e \'tell application "Fixture" to get player state\''
        self.assertEqual(argo.shortcut_commands('pause fixture',[both,state]),[both])   # an act with its own check in one script stays
        framed='osascript -e \'tell application "System Events"\' -e \'tell process "Fixture" to get name of every window\' -e \'end tell\''
        self.assertEqual(argo.shortcut_commands('windows',[framed]),[])

    def test_replay_says_the_outcome_not_how_the_first_run_went(self):
        play='osascript -e \'tell application "Fixture" to play\''
        (self.root/'skills.json').write_text(json.dumps({'unpause fixture':{'cmds':[play],'reply':'Fixture is playing. The first check still showed it paused, but a second check confirmed it.'}}))
        with patch.object(argo.subprocess,'run',return_value=argo.subprocess.CompletedProcess([],0,'','')):
            self.assertEqual(argo.fast('unpause fixture'),'Fixture is playing.')
        for whole in ['Done: focus mode.','Typed "Hi! See you." into Mail.','Opened 10 Hail Pl. Tell me the city.','Playing 1M. It runs in the background.','I typed your reply into the mail box. It isn’t sent yet.','Notes is open. Do not close it.']:
            self.assertEqual(argo.outcome(whole),whole)

    def test_unsupported_peekaboo_falls_back_without_running(self):
        argo.save_skills({'do fixture':{'cmds':['peekaboo click --id 12'],'reply':'Done.','mine':True}})
        with patch.object(argo.subprocess,'run') as run:self.assertIsNone(argo.replay('do fixture'));run.assert_not_called()
        self.assertIsNone(argo.shortcut_commands('do fixture',[self.commands[-1]+' && open -a Fixture']))
        self.assertIsNone(argo.shortcut_commands('do fixture',[argo.ME+' ask again']))
        reply,saved=argo.remember_workflow('nested fixture',f'Done. [workflow nested fixture | Use the native app.] [replay python3 {argo.ME} ask again]',True,['open Fixture'])
        self.assertTrue(saved);self.assertNotIn('nested fixture',argo.skills())

    def test_native_menu_bypasses_map_capture_but_waits_for_confirmation(self):
        args=('menu','com.argo.fixture','Fixture > Start meeting')
        worker=unittest.mock.Mock(returncode=0,stdout='Clicked Start meeting\n',stderr='')
        with patch.object(argo,'wait_commit',return_value=True),patch.object(argo,'hands_call',return_value=worker) as call,patch.object(argo,'hands_map') as mapping:
            self.assertTrue(argo.hands(*args)[1]);call.assert_called_once_with(list(args),timeout=2);mapping.assert_not_called()
        with patch.object(argo,'wait_commit',return_value=False),patch.object(argo,'hands_call') as call:
            self.assertFalse(argo.hands(*args)[1]);call.assert_not_called()

    def test_guarded_background_open_does_not_poll_or_sleep(self):
        with patch.object(argo,'osa') as osa,patch.object(argo.time,'sleep') as sleep,patch.object(argo,'preview_app'),patch.object(argo.subprocess,'run',return_value=unittest.mock.Mock(returncode=0)):
            argo.show('Fixture',bg=True);osa.assert_not_called();sleep.assert_not_called()

    def test_failed_direct_open_falls_back_instead_of_claiming_success(self):
        argo.save_skills({'open fixture':{'cmds':[argo.SHOW+' Fixture'],'reply':'Opened.','mine':True}})
        with patch.object(argo,'show',return_value='no app or file called "Fixture"'):
            self.assertIsNone(argo.replay('open fixture'))

    def test_recent_memory_creates_missing_scratch_directory(self):
        missing=self.root/'new';recent=missing/'recent.jsonl'
        with patch.object(argo,'DIR',str(missing)),patch.object(argo,'RECENT',str(recent)):
            argo.remember_turn('Find fixture notes','Found them.');self.assertEqual(argo.recent()[0]['q'],'Find fixture notes')
            self.assertEqual(recent.stat().st_mode&0o777,0o600)
            with patch.object(argo.os,'replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): argo.remember_turn('Other ask','Other answer')
            self.assertEqual(argo.recent()[0]['q'],'Find fixture notes')

    def test_first_ai_answer_saves_memory_and_log_in_a_fresh_directory(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        missing=self.root/'fresh';brain=unittest.mock.Mock(return_value=('Found them. [unlearn]',0,[]));brain.ok=True;brain.cmds=[];brain.ran=[];brain.observed=[]
        with patch.object(argo,'DIR',str(missing)),patch.object(argo,'RECENT',str(missing/'recent.jsonl')),patch.object(argo,'MEMORY',str(missing/'memory.md')),patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','Find fixture notes']),patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            argo.main();self.assertEqual(argo.recent()[0]['a'],'Found them.');self.assertTrue((missing/'log.jsonl').exists())
        brain.assert_called_once()

    def test_bare_running_check_is_dropped_and_a_new_shortcut_or_workflow_shows_the_learned_pill(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        quit,check='osascript -e \'tell application "Fixture" to quit\'','osascript -e \'application "Fixture" is running\''
        self.assertEqual(argo.shortcut_commands('close fixture',[quit,check]),[quit])
        self.assertEqual(argo.shortcut_commands('close fixture',[f'{quit} && sleep 1 && {check.replace("is","is not")}']),[quit])
        self.assertIsNone(argo.shortcut_commands('close fixture',[f'{check} && {quit}']))   # a check before the act still refuses
        guarded='osascript -e \'tell application "Fixture"\' -e \'if player state is playing then pause\' -e \'end tell\''
        self.assertEqual(argo.shortcut_commands('pause fixture',[guarded]),[guarded])
        def ask(task,reply,cmds):
            brain=unittest.mock.Mock(return_value=(reply,0,[]));brain.ok=True;brain.cmds=cmds;brain.ran=cmds;brain.observed=[]
            tip=unittest.mock.Mock()
            with patch.object(argo,'DIR',str(self.root)),patch.object(argo,'RECENT',str(self.root/'recent.jsonl')),patch.object(argo,'MEMORY',str(self.root/'memory.md')),patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py',task]),patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=tip,look=lambda:[],hands_map=lambda *a:None,cached_hands=lambda:None):
                with patch.object(argo,'app_id',return_value='com.example.fixture'),patch.object(argo,'app_running',return_value=False): argo.main()
            return tip.call_args.args[1]
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'Learned: Say “Close fixture” any time.')
        self.assertEqual(argo.skills()['close fixture']['cmds'],[quit])
        self.assertEqual(argo.recent()[-1]['shortcut']['key'],'close fixture')
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'')   # already known: no pill
        self.assertEqual(ask('Tidy fixture','Tidied. [workflow tidy fixture | Use the View menu.]',[f'{argo.HANDS} see Fixture']),'Learned: Procedure saved for next time.')

    def test_instant_quit_uses_bundle_id_verifies_and_beats_old_skill(self):
        old='osascript -e \'tell application "Fixture Display" to quit\''
        argo.save_skills({'close fixture display':{'cmds':[old],'reply':'Old false success.','mine':True},
                             'end fixture':{'cmds':[old],'reply':'Ended.','mine':True}})
        resolve=lambda name: 'Fixture' if name == 'fixture display' else None
        with patch.object(argo,'app_named',side_effect=resolve),patch.object(argo,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(argo,'quit_app',return_value=True) as quit_app,patch.object(argo,'replay') as replay:
            self.assertEqual(argo.fast('close fixture display'),'Closed Fixture.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');replay.assert_not_called()
            self.assertIn('application id "com.example.fixture"',argo.fast.cmds[0])
            self.assertIsNone(argo.fast('close this tab'))
            self.assertIsNone(argo.fast('close the window'))
        with patch.object(argo,'app_named',side_effect=resolve),patch.object(argo,'app_id',return_value='com.example.fixture'), \
             patch.object(argo,'quit_app',return_value=False):
            self.assertEqual(argo.fast('quit fixture display'),'Fixture is still open.')
            self.assertEqual(argo.fast.cmds,[])
        with patch.object(argo,'app_named',return_value='Fixture'),patch.object(argo,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(argo,'quit_app',return_value=True) as quit_app,patch.object(argo.subprocess,'run') as shell:
            self.assertEqual(argo.replay('end fixture'),'Ended.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');shell.assert_not_called()
        with patch.object(argo,'app_running',side_effect=[True,True,False]),patch.object(argo,'osa') as osa,patch.object(argo.time,'sleep'):
            self.assertTrue(argo.quit_app('com.example.fixture'))
        osa.assert_called_once_with('tell application id "com.example.fixture" to quit',timeout=2)

    def test_user_reported_failure_unlearns_without_saving_the_correction(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        argo.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(argo.subprocess,'run',return_value=worker),patch.object(argo,'preview_commands'):
            answer=argo.fast('hide fixture')
        self.assertEqual(answer,'Fixture is hidden.')
        argo.remember_turn('hide fixture',answer,argo.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('Fixture is hidden now. [unlearn] [workflow hide fixture | Hide it, then check.]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[command];brain.observed=[{'action':command,'error':False,'result':'verified hidden'}]
        say=unittest.mock.Mock()
        with patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','It is still visible']), \
             patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            argo.main()
        self.assertEqual(say.call_args.args[1],'Fixture is hidden now.')   # no control tag shows, and the redo saves nothing
        self.assertEqual(argo.workflows(),{})
        prompt=brain.call_args.args[0]
        self.assertIn('Previous learned shortcut',prompt)
        self.assertIn('hide fixture',prompt)
        self.assertIn('fixture became hidden',prompt)
        self.assertEqual(brain.call_args.kwargs['request'],'It is still visible')
        self.assertNotIn('hide fixture',argo.skills())

    def test_unrelated_ask_after_replay_keeps_the_shortcut(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        argo.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(argo.subprocess,'run',return_value=worker),patch.object(argo,'preview_commands'):
            answer=argo.fast('hide fixture')
        argo.remember_turn('hide fixture',answer,argo.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('The unrelated answer.',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[];brain.observed=[]
        with patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','Explain an unrelated topic']), \
             patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            argo.main()
        self.assertIn('Previous learned shortcut',brain.call_args.args[0])
        self.assertIn('hide fixture',argo.skills())

    def test_stray_unlearn_control_is_never_shown(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('Done. [unlearn]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[];brain.observed=[]
        say=unittest.mock.Mock()
        with patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','Do the fixture task']), \
             patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            argo.main()
        self.assertEqual(say.call_args.args[1],'Done.')
        self.assertEqual(argo.recent()[-1]['a'],'Done.')

    def test_failed_replay_is_redone_and_successful_recovery_replaces_it(self):
        quit='osascript -e \'tell application "Fixture" to quit\''
        argo.save_skills({'bye fixture':{'cmds':[quit],'reply':'Fixture is closed.','mine':True}})
        stubs=dict(app_id=lambda *a:'com.example.fixture',osa=lambda *a,**k:'',app_named=lambda *a:None)
        with patch.multiple(argo,**stubs),patch.object(argo,'app_running',side_effect=[True,False]),patch.object(argo.time,'sleep'),patch.object(argo.subprocess,'run') as shell:
            self.assertEqual(argo.fast('bye fixture'),'Fixture is closed.')   # verified: the same instant reply
            self.assertIsNone(argo.fast.failed);shell.assert_not_called()
        with patch.object(argo,'wants_focus',return_value=True),patch.multiple(argo,**stubs),patch.object(argo.time,'sleep'),patch.object(argo,'preview_commands'), \
             patch.object(argo.subprocess,'run',return_value=argo.subprocess.CompletedProcess([],0,'','')):
            argo.save_skills({**argo.skills(),'show fixture':{'cmds':['open -a Fixture'],'reply':'Opened.','mine':True}})
            with patch.object(argo,'app_running',return_value=False): self.assertIsNone(argo.replay('show fixture'))
            self.assertEqual(argo.replay.ran[-1],'Fixture => not running')
            with patch.object(argo,'app_running',return_value=True): self.assertEqual(argo.replay('show fixture'),'Opened.')

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        replacement=argo.HANDS+" menu com.example.fixture 'Fixture > Quit'"
        brain=unittest.mock.Mock(return_value=('Fixture is closed now; the shortcut had not quit it. [unlearn]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[replacement]
        brain.observed=[{'action':replacement,'error':False,'result':'Fixture closed'}]
        say,tip=unittest.mock.Mock(),unittest.mock.Mock()
        with patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','bye fixture']),patch.object(argo,'app_running',return_value=True),patch.object(argo.time,'sleep'), \
             patch.multiple(argo,**stubs,front=lambda:('Fixture','Scratch'),screens=lambda:[],describe=lambda *a:'Scratch display',
                            selection_context=lambda:'',screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=tip,look=lambda:[],hands_map=lambda *a:None,report=lambda *a:None,cached_hands=lambda:None):
            argo.main()
        said=[c.args for c in say.call_args_list]
        self.assertIn(('▸','The shortcut did not work. Redoing it'),said)
        self.assertNotIn('Fixture is closed.',[s for _,s in said])   # never the learned success line
        self.assertEqual(said[-1][1],'Fixture is closed now; the shortcut had not quit it.')
        prompt=brain.call_args.args[0]
        self.assertIn('still open',prompt);self.assertIn('failed (see its output): redo the request',prompt)
        self.assertEqual(argo.skills()['bye fixture']['cmds'],[replacement])
        self.assertEqual(tip.call_args.args[1],'Learned: Say “bye fixture” any time.')

    def test_a_quit_that_is_still_running_is_not_learned(self):
        command='osascript -e \'tell application id "com.example.fixture" to quit\''
        with patch.object(argo,'cached_hands',return_value=None),patch.object(argo,'app_running',return_value=True):
            self.assertIsNone(argo.learn('close fixture',[command],'Fixture is closed.'))
        with patch.object(argo,'shortcut_commands',return_value=['osascript -e "']):
            self.assertIsNone(argo.learn('malformed fixture',[command],'Done.'))
        self.assertNotIn('close fixture',argo.skills())

    def test_reference_ask_receives_recent_target_and_agent_history(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        url='https://fixture.example/posts/42'
        agent=self.root/'agents'/('a'*32);agent.mkdir(parents=True)
        argo.private_json(str(agent/'context.json'),{'id':'a'*32,'status':'done','created':time.time(),
                                                       'brief':'Find a useful post','links':[url]})
        (self.root/'worked.json').write_text(json.dumps({'app':'Reader Fixture','window':'Earlier post'}))
        brain=unittest.mock.Mock(return_value=('Opened the earlier post.',0,[]));brain.ok=True;brain.cmds=[];brain.ran=[];brain.observed=[]
        with patch.object(argo,'RECENT',str(self.root/'recent.jsonl')),patch.object(argo,'MEMORY',str(self.root/'memory.md')):
            argo.remember_turn('Find a useful post','Opened '+url)
            with patch.object(argo.threading,'Thread',NoThread),patch('sys.argv',['argo.py','Open that post you opened']),patch.multiple(argo,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
                argo.main()
        prompt=brain.call_args.args[0]
        self.assertIn('Earlier:\nQ: Find a useful post\nA: Opened '+url,prompt)
        self.assertIn('Last task worked in: Reader Fixture "Earlier post"',prompt)
        self.assertIn('Background tasks',prompt);self.assertIn('a'*32,prompt)
        self.assertEqual(brain.call_args.kwargs['request'],'Open that post you opened')
