from abc import ABC, abstractmethod

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


class Embedding(nn.Module):
    """Embedding layer with dropout

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        freeze (bool): If True, the tensor does not get updated in the learning process.
            Equivalent to embedding.weight.requires_grad = False. Default: False.
        dropout (float): The dropout rate of the word embedding. Defaults to 0.2.
    """

    def __init__(self, embed_vecs, freeze=False, dropout=0.2):
        super(Embedding, self).__init__()
        self.embedding = nn.Embedding.from_pretrained(embed_vecs, freeze=freeze, padding_idx=0)
        self.dropout = nn.Dropout(dropout)

    def forward(self, input):
        return self.dropout(self.embedding(input))


class RNNEncoder(ABC, nn.Module):
    """Base class of RNN encoder with dropout

    Args:
        input_size (int): The number of expected features in the input.
        hidden_size (int): The number of features in the hidden state.
        num_layers (int): The number of recurrent layers.
        encoder_dropout (float): The dropout rate of the RNN encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the RNN encoder. Defaults to 0.
    """

    def __init__(self, input_size, hidden_size, num_layers, encoder_dropout=0, post_encoder_dropout=0):
        super(RNNEncoder, self).__init__()
        self.rnn = self._get_rnn(input_size, hidden_size, num_layers, encoder_dropout)
        self.post_encoder_dropout = nn.Dropout(post_encoder_dropout)

    def forward(self, input, length, **kwargs):
        self.rnn.flatten_parameters()
        idx = torch.argsort(length, descending=True)
        length_clamped = length[idx].cpu().clamp(min=1)  # avoid the empty text with length 0
        packed_input = pack_padded_sequence(input[idx], length_clamped, batch_first=True)
        outputs, _ = pad_packed_sequence(self.rnn(packed_input)[0], batch_first=True)
        return self.post_encoder_dropout(outputs[torch.argsort(idx)])

    @abstractmethod
    def _get_rnn(self, input_size, hidden_size, num_layers):
        raise NotImplementedError


class GRUEncoder(RNNEncoder):
    """Bi-directional GRU encoder with dropout

    Args:
        input_size (int): The number of expected features in the input.
        hidden_size (int): The number of features in the hidden state.
        num_layers (int): The number of recurrent layers.
        encoder_dropout (float): The dropout rate of the GRU encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the GRU encoder. Defaults to 0.
    """

    def __init__(self, input_size, hidden_size, num_layers, encoder_dropout=0, post_encoder_dropout=0):
        super(GRUEncoder, self).__init__(input_size, hidden_size, num_layers, encoder_dropout, post_encoder_dropout)

    def _get_rnn(self, input_size, hidden_size, num_layers, dropout):
        return nn.GRU(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout, bidirectional=True)


class LSTMEncoder(RNNEncoder):
    """Bi-directional LSTM encoder with dropout

    Args:
        input_size (int): The number of expected features in the input.
        hidden_size (int): The number of features in the hidden state.
        num_layers (int): The number of recurrent layers.
        encoder_dropout (float): The dropout rate of the LSTM encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the LSTM encoder. Defaults to 0.
    """

    def __init__(self, input_size, hidden_size, num_layers, encoder_dropout=0, post_encoder_dropout=0):
        super(LSTMEncoder, self).__init__(input_size, hidden_size, num_layers, encoder_dropout, post_encoder_dropout)

    def _get_rnn(self, input_size, hidden_size, num_layers, dropout):
        return nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout, bidirectional=True)


class CNNEncoder(nn.Module):
    """Multi-filter-size CNN encoder for text classification with max-pooling

    Args:
        input_size (int): The number of expected features in the input.
        filter_sizes (list): Size of convolutional filters.
        num_filter_per_size (int): The number of filters in convolutional layers in each size. Defaults to 128.
        activation (str): Activation function to be used. Defaults to 'relu'.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the CNN encoder. Defaults to 0.
        num_pool (int): The number of pools for max-pooling.
                        If num_pool = 0, do nothing.
                        If num_pool = 1, do typical max-pooling.
                        If num_pool > 1, do adaptive max-pooling.
        channel_last (bool): Whether to transpose the dimension from (batch_size, num_channel, length) to (batch_size, length, num_channel)
    """

    def __init__(
        self,
        input_size,
        filter_sizes,
        num_filter_per_size,
        activation,
        post_encoder_dropout=0,
        num_pool=0,
        channel_last=False,
    ):
        super(CNNEncoder, self).__init__()
        if not filter_sizes:
            raise ValueError(f"CNNEncoder expect non-empty filter_sizes. " f"Got: {filter_sizes}")
        self.channel_last = channel_last
        self.convs = nn.ModuleList()
        for filter_size in filter_sizes:
            conv = nn.Conv1d(in_channels=input_size, out_channels=num_filter_per_size, kernel_size=filter_size)
            self.convs.append(conv)
        self.num_pool = num_pool
        if num_pool > 1:
            self.pool = nn.AdaptiveMaxPool1d(num_pool)
        self.activation = getattr(torch, activation, getattr(F, activation))
        self.post_encoder_dropout = nn.Dropout(post_encoder_dropout)

    def forward(self, input):
        h = input.transpose(1, 2)  # (batch_size, input_size, length)
        h_list = []
        for conv in self.convs:
            h_sub = conv(h)  # (batch_size, num_filter, length)
            if self.num_pool == 1:
                # (batch_size, num_filter, 1)
                h_sub = F.max_pool1d(h_sub, h_sub.shape[2])
            elif self.num_pool > 1:
                h_sub = self.pool(h_sub)  # (batch_size, num_filter, num_pool)
            h_list.append(h_sub)
        h = torch.cat(h_list, 1)  # (batch_size, total_num_filter, *)
        if self.channel_last:
            h = h.transpose(1, 2)  # (batch_size, *, total_num_filter)
        h = self.activation(h)
        return self.post_encoder_dropout(h)


class LabelwiseAttention(nn.Module):
    """Applies attention technique to summarize the sequence for each label
    See `Explainable Prediction of Medical Codes from Clinical Text <https://aclanthology.org/N18-1100.pdf>`_

    Args:
        input_size (int): The number of expected features in the input.
        num_classes (int): Total number of classes.
    """

    def __init__(self, input_size, num_classes):
        super(LabelwiseAttention, self).__init__()
        self.attention = nn.Linear(input_size, num_classes, bias=False)

    def forward(self, input):
        # (batch_size, num_classes, sequence_length)
        attention = self.attention(input).transpose(1, 2)
        attention = F.softmax(attention, -1)
        # (batch_size, num_classes, hidden_dim)
        logits = torch.bmm(attention, input)
        return logits, attention


class LabelwiseMultiHeadAttention(nn.Module):
    """Labelwise multi-head attention

    Args:
        input_size (int): The number of expected features in the input.
        num_classes (int): Total number of classes.
        num_heads (int): The number of parallel attention heads.
        dropout (float): The dropout rate for the attention. Defaults to 0.
    """

    def __init__(self, input_size, num_classes, num_heads, dropout=0):
        super(LabelwiseMultiHeadAttention, self).__init__()
        self.attention = nn.MultiheadAttention(embed_dim=input_size, num_heads=num_heads, dropout=dropout)
        self.Q = nn.Linear(input_size, num_classes)

    def forward(self, input, attention_mask=None):
        # (sequence_length, batch_size, hidden_dim)
        key = value = input.permute(1, 0, 2)
        query = self.Q.weight.repeat(input.size(0), 1, 1).transpose(0, 1)  # (num_classes, batch_size, hidden_dim)

        logits, attention = self.attention(query, key, value, key_padding_mask=attention_mask)
        # (batch_size, num_classes, hidden_dim)
        logits = logits.permute(1, 0, 2)
        return logits, attention


class LabelwiseLinearOutput(nn.Module):
    """Applies a linear transformation to the incoming data for each label

    Args:
        input_size (int): The number of expected features in the input.
        num_classes (int): Total number of classes.
    """

    def __init__(self, input_size, num_classes):
        super(LabelwiseLinearOutput, self).__init__()
        self.output = nn.Linear(input_size, num_classes)

    def forward(self, input):
        return (self.output.weight * input).sum(dim=-1) + self.output.bias


class PartialLabelwiseAttention(nn.Module):
    """Similar to LabelwiseAttention.
    What makes the class different from LabelwiseAttention is that only the weights of selected labels will be
    updated in a single iteration.
    """

    def __init__(self, hidden_size, num_classes):
        super().__init__()
        self.attention = nn.Embedding(num_classes + 1, hidden_size)

    def forward(self, inputs, labels_selected):
        attn_inputs = inputs.transpose(1, 2)  # batch_size, hidden_dim, length
        attn_weights = self.attention(labels_selected)  # batch_size, sample_size, hidden_dim
        attention = attn_weights @ attn_inputs  # batch_size, sample_size, length
        attention = F.softmax(attention, -1)  # batch_size, sample_size, length
        logits = attention @ inputs  # batch_size, sample_size, hidden_dim
        return logits, attention


class MultilayerLinearOutput(nn.Module):
    def __init__(self, linear_size, output_size):
        super().__init__()
        self.linears = nn.ModuleList(nn.Linear(in_s, out_s) for in_s, out_s in zip(linear_size[:-1], linear_size[1:]))
        self.output = nn.Linear(linear_size[-1], output_size)

    def forward(self, inputs):
        linear_out = inputs
        for linear in self.linears:
            linear_out = F.relu(linear(linear_out))
        return torch.squeeze(self.output(linear_out), -1)
