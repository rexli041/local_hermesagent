<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <http://www.gnu.org/licenses/>.

/**
 * Privacy provider tests for local_hermesagent.
 *
 * @package    local_hermesagent
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

namespace local_hermesagent;

use core_privacy\local\metadata\collection;
use core_privacy\local\request\approved_contextlist;
use core_privacy\local\request\writer;
use context_system;
use local_hermesagent\privacy\provider;

defined('MOODLE_INTERNAL') || die();

global $CFG;
require_once($CFG->dirroot . '/lib/setup.php');

/**
 * Privacy provider test cases.
 *
 * @covers \local_hermesagent\privacy\provider
 */
final class privacy_test extends \core_privacy\tests\provider_testcase {

    /** @var stdClass User with data */
    protected $userWithData;
    /** @var stdClass User without data */
    protected $userNoData;
    /** @var stdClass A conversation for $userWithData */
    protected $conversation;

    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest(true);

        $this->userWithData = self::getDataGenerator()->create_user();
        $this->userNoData = self::getDataGenerator()->create_user();

        // Create a conversation for userWithData.
        $now = time();
        $this->conversation = new \stdClass();
        $this->conversation->name = get_string('newconversation', 'local_hermesagent');
        $this->conversation->usermodified = $this->userWithData->id;
        $this->conversation->timecreated = $now;
        $this->conversation->timemodified = $now;
        $this->conversation->id = $GLOBALS['DB']->insert_record(
            'local_hermesagent_conversations',
            $this->conversation
        );

        // Create a couple of messages.
        foreach (['user', 'assistant'] as $role) {
            $msg = new \stdClass();
            $msg->conversationid = $this->conversation->id;
            $msg->role = $role;
            $msg->content = "Test message from {$role}";
            $msg->timemodified = $now;
            $GLOBALS['DB']->insert_record('local_hermesagent_messages', $msg);
        }
    }

    // ------------------------------------------------------------------
    // get_metadata()
    // ------------------------------------------------------------------

    public function test_get_metadata_returns_expected_tables(): void {
        $collection = new collection('local_hermesagent');
        $result = provider::get_metadata($collection);
        $items = $result->get_collection();

        // We expect exactly two database table entries.
        $this->assertCount(2, $items);

        $tableNames = array_map(function ($item) {
            return $item->get_name();
        }, array_keys($items));

        $this->assertContains('local_hermesagent_conversations', $tableNames);
        $this->assertContains('local_hermesagent_messages', $tableNames);
    }

    // ------------------------------------------------------------------
    // get_contexts_for_userid()
    // ------------------------------------------------------------------

    public function test_get_contexts_for_userid_returns_system_context_when_user_has_conversations(): void {
        $contextlist = provider::get_contexts_for_userid($this->userWithData->id);
        $contexts = $contextlist->get_contextids();

        $this->assertCount(1, $contexts);
        $this->assertEquals(context_system::instance()->id, reset($contexts));
    }

    public function test_get_contexts_for_userid_returns_empty_when_user_has_no_conversations(): void {
        $contextlist = provider::get_contexts_for_userid($this->userNoData->id);
        $contexts = $contextlist->get_contextids();

        $this->assertEmpty($contexts);
    }

    // ------------------------------------------------------------------
    // delete_data_for_user()
    // ------------------------------------------------------------------

    public function test_delete_data_for_user_removes_conversations_and_messages(): void {
        global $DB;

        $systemcontext = context_system::instance();
        $contextlist = new approved_contextlist($this->userWithData, 'local_hermesagent', [$systemcontext->id]);

        provider::delete_data_for_user($contextlist);

        // Conversations should be gone.
        $this->assertEquals(
            0,
            $DB->count_records('local_hermesagent_conversations', ['usermodified' => $this->userWithData->id])
        );

        // Messages should also be gone.
        $this->assertEquals(0, $DB->count_records('local_hermesagent_messages'));
    }

    public function test_delete_data_for_user_does_not_affect_other_users(): void {
        global $DB;

        // Create a second conversation for another user.
        $otheruser = self::getDataGenerator()->create_user();
        $otherconv = new \stdClass();
        $otherconv->name = get_string('newconversation', 'local_hermesagent');
        $otherconv->usermodified = $otheruser->id;
        $otherconv->timecreated = time();
        $otherconv->timemodified = time();
        $otherconv->id = $DB->insert_record('local_hermesagent_conversations', $otherconv);

        $othermsg = new \stdClass();
        $othermsg->conversationid = $otherconv->id;
        $othermsg->role = 'user';
        $othermsg->content = 'Other user message';
        $othermsg->timemodified = time();
        $DB->insert_record('local_hermesagent_messages', $othermsg);

        // Now delete data for $this->userWithData only.
        $systemcontext = context_system::instance();
        $contextlist = new approved_contextlist($this->userWithData, 'local_hermesagent', [$systemcontext->id]);
        provider::delete_data_for_user($contextlist);

        // Other user's data must still be there.
        $this->assertEquals(1, $DB->count_records('local_hermesagent_conversations', ['usermodified' => $otheruser->id]));
        $this->assertEquals(1, $DB->count_records('local_hermesagent_messages'));
    }

    // ------------------------------------------------------------------
    // export_user_data()  (writer-based export)
    // ------------------------------------------------------------------

    public function test_export_user_data_writes_conversation_data(): void {
        $systemcontext = context_system::instance();
        $contextlist = new approved_contextlist($this->userWithData, 'local_hermesagent', [$systemcontext->id]);

        provider::export_user_data($contextlist);

        $exported = writer::with_context($systemcontext)->get_data(
            [get_string('privacy:conversations', 'local_hermesagent')]
        );

        $this->assertNotNull($exported);
        $this->assertObjectHasAttribute('id', $exported);
        $this->assertEquals($this->conversation->id, $exported->id);
    }
}
