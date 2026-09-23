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
      requestId promptVersion latencyMs intent confidence nluSource entities route fallbackUsed
      toolCalls { name args ok latencyMs }
      llmCalls { step provider model latencyMs inputTokens outputTokens }
      retrievedChunks { chunkId collection section score used }
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
