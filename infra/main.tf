terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  lambda_source_files = concat(
    [for file in fileset(path.module, "../src/triage") : "${path.module}/../src/triage/${file}"],
    ["${path.module}/../rules/rules.yaml", "${path.module}/../requirements.txt", "${path.module}/../scripts/build_lambda.sh"]
  )
}

resource "terraform_data" "lambda_package" {
  triggers_replace = [for file in local.lambda_source_files : filesha256(file)]
  provisioner "local-exec" {
    command = "bash ${path.module}/../scripts/build_lambda.sh ${path.module}"
  }
}

data "archive_file" "triage_lambda" {
  depends_on  = [terraform_data.lambda_package]
  type        = "zip"
  source_dir  = "${path.module}/.terraform-build/package"
  output_path = "${path.module}/.terraform-build/triage-lambda.zip"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "triage_lambda" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.inbox.arn}/*"]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.idempotency.arn, aws_dynamodb_table.decisions_outbox.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.outbox.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-ingest:*"]
  }
}

data "aws_iam_policy_document" "relay_lambda" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.outbox.arn]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.decisions_outbox.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-relay:*"]
  }
}

resource "aws_s3_bucket" "inbox" {
  bucket        = "${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "inbox" {
  bucket                  = aws_s3_bucket.inbox.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_notification" "inbox" {
  bucket      = aws_s3_bucket.inbox.id
  eventbridge = true
}

resource "aws_ses_receipt_rule_set" "inbound" {
  rule_set_name = "${var.project_name}-receipt-rules"
}

resource "aws_ses_active_receipt_rule_set" "inbound" {
  rule_set_name = aws_ses_receipt_rule_set.inbound.rule_set_name
}

resource "aws_ses_receipt_rule" "store_in_s3" {
  name          = "store-inbox-objects"
  rule_set_name = aws_ses_receipt_rule_set.inbound.rule_set_name
  enabled       = true
  scan_enabled  = true
  tls_policy    = "Require"
  recipients    = [var.inbound_recipient_domain]
  s3_action {
    bucket_name = aws_s3_bucket.inbox.id
    position    = 1
  }
}

resource "aws_dynamodb_table" "idempotency" {
  name         = "${var.project_name}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"
  attribute {
    name = "idempotency_key"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "decisions_outbox" {
  name         = "${var.project_name}-decisions-outbox"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
}

resource "aws_sqs_queue" "outbox_dlq" {
  name                      = "${var.project_name}-outbox-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "outbox" {
  name                       = "${var.project_name}-outbox"
  visibility_timeout_seconds = 180
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.outbox_dlq.arn, maxReceiveCount = 5 })
}

resource "aws_iam_role" "ingest_lambda" {
  name               = "${var.project_name}-ingest-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}
resource "aws_iam_role_policy" "ingest_lambda" {
  role   = aws_iam_role.ingest_lambda.id
  policy = data.aws_iam_policy_document.triage_lambda.json
}
resource "aws_iam_role" "relay_lambda" {
  name               = "${var.project_name}-relay-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}
resource "aws_iam_role_policy" "relay_lambda" {
  role   = aws_iam_role.relay_lambda.id
  policy = data.aws_iam_policy_document.relay_lambda.json
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.project_name}-ingest"
  role             = aws_iam_role.ingest_lambda.arn
  handler          = "triage.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.triage_lambda.output_path
  source_code_hash = data.archive_file.triage_lambda.output_base64sha256
  timeout          = 30
  environment { variables = { TRIAGE_RULES_PATH = "rules/rules.yaml", TRIAGE_DRY_RUN = "0" } }
}

resource "aws_lambda_function" "relay" {
  function_name    = "${var.project_name}-relay"
  role             = aws_iam_role.relay_lambda.arn
  handler          = "triage.handler.relay_lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.triage_lambda.output_path
  source_code_hash = data.archive_file.triage_lambda.output_base64sha256
  timeout          = 30
}

resource "aws_cloudwatch_event_rule" "s3_created" {
  name          = "${var.project_name}-s3-created"
  event_pattern = jsonencode({ source = ["aws.s3"], detail-type = ["Object Created"], detail = { bucket = { name = [aws_s3_bucket.inbox.id] } } })
}
resource "aws_cloudwatch_event_target" "ingest" {
  rule = aws_cloudwatch_event_rule.s3_created.name
  arn  = aws_lambda_function.ingest.arn
}
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeS3ObjectCreated"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.s3_created.arn
}
resource "aws_lambda_event_source_mapping" "relay" {
  event_source_arn = aws_sqs_queue.outbox.arn
  function_name    = aws_lambda_function.relay.arn
  batch_size       = 10
}
