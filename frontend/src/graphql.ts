import { gql } from "@apollo/client";

const MESSAGE_FIELDS = gql`
  fragment MessageFields on Message {
    id
    role
    content
    createdAt
    suggestions
    products { id name brand category price rating stock }
    order {
      id status total carrier trackingNumber placedAt deliveredAt
      items { name quantity unitPrice }
    }
    sources { source section chunkId score }
  }
`;

const RESPONSE_FIELDS = gql`
  ${MESSAGE_FIELDS}
  fragment ResponseFields on ChatResponse {
    conversationId
    message { ...MessageFields }
    debug {
      requestId promptVersion latencyMs intent confidence nluSource entities route fallbackUsed historyMessagesUsed
      toolCalls { name args output ok latencyMs error }
      llmCalls { step provider model latencyMs inputTokens outputTokens }
      retrievedChunks { chunkId collection source section score used content }
      guardrails { name stage passed action score detail }
    }
  }
`;

// Streaming (graphql-ws): token events, then a final guardrail-validated response
export const SEND_MESSAGE_STREAM = gql`
  ${RESPONSE_FIELDS}
  subscription SendMessageStream($input: SendMessageInput!) {
    sendMessageStream(input: $input) {
      type
      token
      errorCode
      errorMessage
      response { ...ResponseFields }
    }
  }
`;

export const SUBMIT_FEEDBACK = gql`
  mutation SubmitFeedback($input: FeedbackInput!) {
    submitFeedback(input: $input)
  }
`;

export const GET_CONVERSATION = gql`
  ${MESSAGE_FIELDS}
  query GetConversation($id: String!) {
    conversation(id: $id) {
      id
      messages { ...MessageFields }
    }
  }
`;

export const CLEAR_CONVERSATION = gql`
  mutation ClearConversation($id: String!) {
    clearConversation(id: $id)
  }
`;

export const LOGIN = gql`
  mutation Login($email: String!, $password: String!) {
    login(email: $email, password: $password) {
      token
      user { id email fullName }
    }
  }
`;

export const ME = gql`
  query Me {
    me { id email fullName }
  }
`;

export const DEMO_USERS = gql`
  query DemoUsers {
    demoUsers { id email fullName orderCount }
  }
`;

// ---------- AI Testing Lab ----------
const LAB_USER_FIELDS = gql`
  fragment LabUserFields on LabUser {
    id email fullName role active createdAt lastLoginAt
  }
`;

export const LAB_SIGNUP = gql`
  ${LAB_USER_FIELDS}
  mutation LabSignup($input: LabSignupInput!) {
    labSignup(input: $input) { token user { ...LabUserFields } }
  }
`;

export const LAB_LOGIN = gql`
  ${LAB_USER_FIELDS}
  mutation LabLogin($email: String!, $password: String!) {
    labLogin(email: $email, password: $password) { token user { ...LabUserFields } }
  }
`;

export const LAB_ME = gql`
  ${LAB_USER_FIELDS}
  query LabMe {
    labMe { ...LabUserFields }
  }
`;

export const LAB_PROGRESS = gql`
  query LabProgress {
    labProgress { lessonId completedAt }
  }
`;

export const COMPLETE_LESSON = gql`
  mutation CompleteLesson($lessonId: String!) {
    completeLesson(lessonId: $lessonId) { lessonId completedAt }
  }
`;

export const LAB_USERS = gql`
  query LabUsers {
    labUsers { id email fullName role active createdAt lastLoginAt lessonsCompleted }
  }
`;

export const LAB_UPDATE_USER = gql`
  ${LAB_USER_FIELDS}
  mutation LabUpdateUser($id: Int!, $role: String, $active: Boolean) {
    labUpdateUser(id: $id, role: $role, active: $active) { ...LabUserFields }
  }
`;
