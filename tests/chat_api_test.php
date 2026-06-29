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
 * PHPUnit tests for local_hermesagent external web services (chat_api).
 *
 * @package    local_hermesagent
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

namespace local_hermesagent\external;

use externallib_advanced_testcase;
use context_system;

defined('MOODLE_INTERNAL') || die();

global $CFG;
require_once($CFG->dirroot . '/lib/externallib.php');
require_once(__DIR__ . '/../../classes/external/chat_api.php');

/**
 * Chat API external function tests.
 *
 * @covers \local_hermesagent\external\chat_api
 */
final class chat_api_test extends externallib_advanced_testcase {

    /** @var stdClass User 1 */
    protected $user1;
    /** @var stdClass User 2 */
    protected $user2;

    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest(true);
        $this->user1 = self::getDataGenerator()->create_user();
        $this->user2 = self::getDataGenerator()->create_user();

        // Grant both users the 'use' capability.
        self::assignUserCapability('local/hermesagent:use', context_system::instance()->id, $this->user1->id);
        self::assignUserCapability('local/hermesagent:use', context_system::instance()->id, $this->user2->id);
    }

    /**
     * Helper: create a conversation record for a given user.
     */
    private function create_conversation(stdClass $user): stdClass {
        global $DB;
        $now = time();
        $conv = new \stdClass();
        $conv->name = get_string('newconversation', 'local_hermesagent');
        $conv->usermodified = $user->id;
        $conv->timecreated = $now;
        $conv->timemodified = $now;
        $conv->id = $DB->insert_record('local_hermesagent_conversations', $conv);
        return $DB->get_record('local_hermesagent_conversations', ['id' => $conv->id], '*', MUST_EXIST);
    }

    /**
     * Helper: create a message record.
     */
    private function create_message(int $convid, string $role, string $content): stdClass {
        global $DB;
        $rec = new \stdClass();
        $rec->conversationid = $convid;
        $rec->role = $role;
        $rec->content = $content;
        $rec->timemodified = time();
        $rec->id = $DB->insert_record('local_hermesagent_messages', $rec);
        return $DB->get_record('local_hermesagent_messages', ['id' => $rec->id], '*', MUST_EXIST);
    }

    // ------------------------------------------------------------------
    // get_conversations() tests
    // ------------------------------------------------------------------

    public function test_get_conversations_returns_empty_for_new_user(): void {
        global $DB;
        $this->setUser($this->user1);

        $result = chat_api::get_conversations();
        $result = external_api::clean_returnvalue(
            chat_api::get_conversations_returns(),
            $result
        );

        $this->assertIsArray($result['conversations']);
        $this->assertEmpty($result['conversations']);
        $this->assertEquals(0, $DB->count_records('local_hermesagent_conversations'));
    }

    public function test_get_conversations_returns_own_conversations(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);
        // Also create one for user2 to confirm isolation.
        $this->create_conversation($this->user2);

        $result = chat_api::get_conversations();
        $result = external_api::clean_returnvalue(
            chat_api::get_conversations_returns(),
            $result
        );

        $this->assertCount(1, $result['conversations']);
        $this->assertEquals($conv->id, $result['conversations'][0]['id']);
    }

    // ------------------------------------------------------------------
    // send_message() tests
    // ------------------------------------------------------------------

    public function test_send_message_creates_message(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);

        $result = chat_api::send_message($conv->id, 'Hello Hermes');
        $result = external_api::clean_returnvalue(
            chat_api::send_message_returns(),
            $result
        );

        $this->assertArrayHasKey('messageid', $result);
        $this->assertGreaterThan(0, $result['messageid']);
        $this->assertEquals($conv->id, $result['conversationid']);

        $msg = $DB->get_record('local_hermesagent_messages', ['id' => $result['messageid']], '*', MUST_EXIST);
        $this->assertEquals('user', $msg->role);
        $this->assertEquals('Hello Hermes', $msg->content);
    }

    public function test_send_message_rejects_another_users_conversation(): void {
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user2);

        $this->expectException(\moodle_exception::class);
        $this->expectExceptionMessage('invalidconversation');
        chat_api::send_message($conv->id, 'Hello from user1');
    }

    // ------------------------------------------------------------------
    // get_history() tests
    // ------------------------------------------------------------------

    public function test_get_history_returns_own_messages(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);
        $msg1 = $this->create_message($conv->id, 'user', 'Hi');
        $msg2 = $this->create_message($conv->id, 'assistant', 'Hello!');

        $result = chat_api::get_history($conv->id);
        $result = external_api::clean_returnvalue(
            chat_api::get_history_returns(),
            $result
        );

        $this->assertCount(2, $result['messages']);
        $this->assertEquals('user', $result['messages'][0]['role']);
        $this->assertEquals('Hi', $result['messages'][0]['content']);
        $this->assertEquals('assistant', $result['messages'][1]['role']);
        $this->assertEquals('Hello!', $result['messages'][1]['content']);
    }

    public function test_get_history_rejects_another_users_conversation(): void {
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user2);
        $this->create_message($conv->id, 'user', 'secret message');

        $this->expectException(\moodle_exception::class);
        $this->expectExceptionMessage('invalidconversation');
        chat_api::get_history($conv->id);
    }

    // ------------------------------------------------------------------
    // delete_conversation() tests
    // ------------------------------------------------------------------

    public function test_delete_conversation_by_owner(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);
        $this->create_message($conv->id, 'user', 'delete me');

        $result = chat_api::delete_conversation($conv->id);
        $result = external_api::clean_returnvalue(
            chat_api::delete_conversation_returns(),
            $result
        );

        $this->assertTrue($result['deleted']);
        $this->assertFalse($DB->record_exists('local_hermesagent_conversations', ['id' => $conv->id]));
        $this->assertEquals(0, $DB->count_records('local_hermesagent_messages'));
    }

    public function test_delete_conversation_requires_ownership(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user2);

        $result = chat_api::delete_conversation($conv->id);
        $result = external_api::clean_returnvalue(
            chat_api::delete_conversation_returns(),
            $result
        );

        $this->assertTrue($result['deleted']);
        // Conversation should still exist (owner mismatch, silent no-op in code).
        $this->assertTrue($DB->record_exists('local_hermesagent_conversations', ['id' => $conv->id]));
    }

    // ------------------------------------------------------------------
    // rename_conversation() tests
    // ------------------------------------------------------------------

    public function test_rename_conversation_by_owner(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);

        $result = chat_api::rename_conversation($conv->id, 'My new name');
        $result = external_api::clean_returnvalue(
            chat_api::rename_conversation_returns(),
            $result
        );

        $this->assertEquals('ok', $result['status']);
        $updated = $DB->get_field('local_hermesagent_conversations', 'name', ['id' => $conv->id]);
        $this->assertEquals('My new name', $updated);
    }

    public function test_rename_conversation_requires_ownership(): void {
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user2);

        $this->expectException(\moodle_exception::class);
        $this->expectExceptionMessage('invalidconversation');
        chat_api::rename_conversation($conv->id, 'Hacked name');
    }

    // ------------------------------------------------------------------
    // save_assistant_response() tests
    // ------------------------------------------------------------------

    public function test_save_assistant_response_by_owner(): void {
        global $DB;
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user1);

        $result = chat_api::save_assistant_response($conv->id, 'AI response here');
        $result = external_api::clean_returnvalue(
            chat_api::save_assistant_response_returns(),
            $result
        );

        $this->assertEquals('ok', $result['status']);
        $msg = $DB->get_records('local_hermesagent_messages', ['conversationid' => $conv->id]);
        $this->assertCount(1, $msg);
        $last = reset($msg);
        $this->assertEquals('assistant', $last->role);
        $this->assertEquals('AI response here', $last->content);
    }

    public function test_save_assistant_response_requires_ownership(): void {
        $this->setUser($this->user1);

        $conv = $this->create_conversation($this->user2);

        $this->expectException(\moodle_exception::class);
        $this->expectExceptionMessage('invalidconversation');
        chat_api::save_assistant_response($conv->id, 'Hijacked response');
    }
}
