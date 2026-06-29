@local @local_hermesagent @local_hermesagent_chat
Feature: Access and use the Hermes Agent chat interface

  In order to interact with the AI assistant
  As a teacher
  I need to be able to access the chat page and send messages

  Background:
    Given the following "users" exist:
      | username | firstname | lastname | email                |
      | teacher1 | Teacher   | One      | teacher1@example.com |
    And the following "courses" exist:
      | fullname | shortname |
      | Course 1 | C1        |
    And the following "course enrolments" exist:
      | user     | course | role           |
      | teacher1 | C1     | editingteacher |
    And the following config values are set as raw sql:
      | rawsql                                                                                         |
      | INSERT INTO {local_hermesagent_settings} (name, value, description, timemodified) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING |

  Scenario: Teacher can navigate to the Hermes chat page
    Given I log in as "teacher1"
    And I am on the "local/hermesagent/chat.php" page
    Then I should see "Hermes Agent"
    And I should see "Conversations"
    And I should see "Ask Hermes anything about your Moodle instance..."

  Scenario: Teacher can see the chat input area and send button
    Given I log in as "teacher1"
    And I am on the "local/hermesagent/chat.php" page
    Then I should see "Send"
    And "#hermes-message-input" "css_element" should exist
    And "#hermes-chat-area" "css_element" should exist

  Scenario: Teacher sees conversation sidebar with new conversation link
    Given I log in as "teacher1"
    And I am on the "local/hermesagent/chat.php" page
    Then I should see "New conversation"
    And ".hermes-sidebar" "css_element" should exist
    And ".hermes-chat-container" "css_element" should exist
