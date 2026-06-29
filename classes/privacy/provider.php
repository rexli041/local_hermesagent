<?php
/**
 * Privacy provider — manages personal data for GDPR compliance.
 *
 * @package    local_hermesagent
 * @copyright  2026
 * @license    https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

namespace local_hermesagent\privacy;

use core_privacy\local\metadata\collection;
use core_privacy\local\request\approved_contextlist;
use core_privacy\local\request\approved_userlist;
use core_privacy\local\request\contextlist;
use core_privacy\local\request\transform;
use core_privacy\local\request\userlist;
use core_privacy\local\request\writer;

/**
 * Privacy provider for local_hermesagent.
 *
 * This plugin stores personal user data:
 * - Chat conversations (user input and assistant responses)
 * - Conversation metadata linked to the user who created/modified them
 */
class provider implements
    \core_privacy\local\metadata\provider,
    \core_privacy\local\request\core_user_data_provider,
    \core_privacy\local\request\core_userlist_provider {

    /**
     * Return metadata about this plugin's data storage.
     */
    public static function get_metadata(collection $collection): collection {
        $collection->add_database_table(
            'local_hermesagent_conversations',
            [
                'id'             => 'privacy:metadata:conversation:id',
                'name'           => 'privacy:metadata:conversation:name',
                'usermodified'   => 'privacy:metadata:conversation:usermodified',
                'acp_session_id' => 'privacy:metadata:conversation:acpsessionid',
                'timemodified'   => 'privacy:metadata:conversation:timemodified',
                'timecreated'    => 'privacy:metadata:conversation:timecreated',
            ],
            'privacy:metadata:conversation'
        );

        $collection->add_database_table(
            'local_hermesagent_messages',
            [
                'id'             => 'privacy:metadata:message:id',
                'conversationid' => 'privacy:metadata:message:conversationid',
                'role'           => 'privacy:metadata:message:role',
                'content'        => 'privacy:metadata:message:content',
                'tool_calls'     => 'privacy:metadata:message:toolcalls',
                'tool_results'   => 'privacy:metadata:message:toolresults',
                'timemodified'   => 'privacy:metadata:message:timemodified',
            ],
            'privacy:metadata:message'
        );

        return $collection;
    }

    /**
     * Get the list of contexts that contain user data for a specified user.
     */
    public static function get_contexts_for_userid(int $userid): contextlist {
        global $DB;

        $contextlist = new contextlist();
        $systemcontext = \context_system::instance();

        $sql = "SELECT 1
                  FROM {local_hermesagent_conversations}
                 WHERE usermodified = :userid
                 LIMIT 1";

        if ($DB->record_exists_sql($sql, ['userid' => $userid])) {
            $contextlist->add($systemcontext);
        }

        return $contextlist;
    }

    /**
     * Export personal data for a given user and context.
     */
    public static function export_user_data(approved_contextlist $contextlist) {
        global $DB;

        if (empty($contextlist->count())) {
            return;
        }

        $user = $contextlist->get_user();
        $systemcontext = \context_system::instance();

        // Export conversations.
        $conversations = $DB->get_records(
            'local_hermesagent_conversations',
            ['usermodified' => $user->id]
        );

        if (empty($conversations)) {
            return;
        }

        $subcontext = [get_string('privacy:conversations', 'local_hermesagent')];

        foreach ($conversations as $conversation) {
            $convdata = [
                'id'             => $conversation->id,
                'name'           => $conversation->name,
                'acp_session_id' => $conversation->acp_session_id ?? '',
                'timecreated'    => transform::datetime($conversation->timecreated),
                'timemodified'   => transform::datetime($conversation->timemodified),
            ];

            writer::with_context($systemcontext)
                ->export_data($subcontext, (object)$convdata);

            // Export messages for this conversation.
            $messages = $DB->get_records(
                'local_hermesagent_messages',
                ['conversationid' => $conversation->id],
                'id ASC'
            );

            if ($messages) {
                $messagesubcontext = $subcontext + [
                    get_string('privacy:messages', 'local_hermesagent'),
                ];

                foreach ($messages as $message) {
                    $messagedata = [
                        'id'             => $message->id,
                        'role'           => $message->role,
                        'content'        => $message->content,
                        'tool_calls'     => $message->tool_calls ?? '',
                        'tool_results'   => $message->tool_results ?? '',
                        'timemodified'   => transform::datetime($message->timemodified),
                    ];

                    writer::with_context($systemcontext)
                        ->export_data($messagesubcontext, (object)$messagedata);
                }
            }
        }
    }

    /**
     * Delete all data for a user in a context.
     */
    public static function delete_data_for_user(approved_contextlist $contextlist) {
        global $DB;

        if (empty($contextlist->count())) {
            return;
        }

        $user = $contextlist->get_user();
        $userid = $user->id;

        // Delete messages first (foreign key constraint via tool_log).
        $sql = "SELECT m.id
                  FROM {local_hermesagent_messages} m
                  JOIN {local_hermesagent_conversations} c ON c.id = m.conversationid
                 WHERE c.usermodified = :userid";
        $messageids = $DB->get_fieldset_sql($sql, ['userid' => $userid]);

        foreach ($messageids as $mid) {
            $DB->delete_records('local_hermesagent_tool_log', ['messageid' => $mid]);
        }

        if (!empty($messageids)) {
            $placeholder = implode(',', array_fill(0, count($messageids), '?'));
            $DB->delete_records_select(
                'local_hermesagent_messages',
                "id IN ($placeholder)",
                $messageids
            );
        }

        // Delete conversations.
        $DB->delete_records('local_hermesagent_conversations', ['usermodified' => $userid]);
    }

    /**
     * Delete all data for a group of users in a context.
     */
    public static function delete_data_for_users(approved_userlist $userlist) {
        global $DB;

        if (empty($userlist->count())) {
            return;
        }

        $userids = $userlist->get_userids();
        $placeholder = implode(',', array_fill(0, count($userids), '?'));

        // Delete tool_log entries for messages belonging to these users' conversations.
        $sql = "SELECT tl.id
                  FROM {local_hermesagent_tool_log} tl
                  JOIN {local_hermesagent_messages} m ON m.id = tl.messageid
                  JOIN {local_hermesagent_conversations} c ON c.id = m.conversationid
                 WHERE c.usermodified IN ($placeholder)";
        $toollogids = $DB->get_fieldset_sql($sql, $userids);

        if (!empty($toollogids)) {
            $tlplaceholder = implode(',', array_fill(0, count($toollogids), '?'));
            $DB->delete_records_select('local_hermesagent_tool_log', "id IN ($tlplaceholder)", $toollogids);
        }

        // Delete messages for these users' conversations.
        $sql = "SELECT m.id
                  FROM {local_hermesagent_messages} m
                  JOIN {local_hermesagent_conversations} c ON c.id = m.conversationid
                 WHERE c.usermodified IN ($placeholder)";
        $messageids = $DB->get_fieldset_sql($sql, $userids);

        if (!empty($messageids)) {
            $mplaceholder = implode(',', array_fill(0, count($messageids), '?'));
            $DB->delete_records_select('local_hermesagent_messages', "id IN ($mplaceholder)", $messageids);
        }

        // Delete conversations.
        $DB->delete_records_list('local_hermesagent_conversations', 'usermodified', $userids);
    }

    /**
     * Get the list of users who have data in a context.
     */
    public static function get_users_in_context(userlist $userlist) {
        global $DB;

        $context = $userlist->get_context();

        if (!$context instanceof \context_system) {
            return;
        }

        $sql = "SELECT usermodified AS id
                  FROM {local_hermesagent_conversations}
                 WHERE usermodified != 0";

        $userlist->add_from_sql($sql);
    }
}
