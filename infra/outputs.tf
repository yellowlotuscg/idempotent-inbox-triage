output "inbox_bucket" {
  value = aws_s3_bucket.inbox.bucket
}

output "idempotency_table" {
  value = aws_dynamodb_table.idempotency.name
}

output "decisions_outbox_table" {
  value = aws_dynamodb_table.decisions_outbox.name
}

output "outbox_queue_url" {
  value = aws_sqs_queue.outbox.url
}

output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
