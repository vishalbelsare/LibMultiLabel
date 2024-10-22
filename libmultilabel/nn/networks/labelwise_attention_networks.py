from abc import ABC, abstractmethod

import torch.nn as nn

from .modules import (
    Embedding,
    GRUEncoder,
    LSTMEncoder,
    CNNEncoder,
    LabelwiseAttention,
    LabelwiseMultiHeadAttention,
    LabelwiseLinearOutput,
    PartialLabelwiseAttention,
    MultilayerLinearOutput,
)


class LabelwiseAttentionNetwork(ABC, nn.Module):
    """Base class for Labelwise Attention Network

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        num_classes (int): Total number of classes.
        embed_dropout (float): The dropout rate of the word embedding.
        encoder_dropout (float): The dropout rate of the encoder.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the encoder.
        hidden_dim (int): The output dimension of the encoder.
    """

    def __init__(self, embed_vecs, num_classes, embed_dropout, encoder_dropout, post_encoder_dropout, hidden_dim):
        super(LabelwiseAttentionNetwork, self).__init__()
        self.embedding = Embedding(embed_vecs, dropout=embed_dropout)
        self.encoder = self._get_encoder(embed_vecs.shape[1], encoder_dropout, post_encoder_dropout)
        self.attention = self._get_attention()
        self.output = LabelwiseLinearOutput(hidden_dim, num_classes)

    @abstractmethod
    def forward(self, input):
        raise NotImplementedError

    @abstractmethod
    def _get_encoder(self, input_size, encoder_dropout, post_encoder_dropout):
        raise NotImplementedError

    @abstractmethod
    def _get_attention(self):
        raise NotImplementedError


class RNNLWAN(LabelwiseAttentionNetwork):
    """Base class for RNN Labelwise Attention Network"""

    def forward(self, input):
        # (batch_size, sequence_length, embed_dim)
        x = self.embedding(input["text"])
        # (batch_size, sequence_length, hidden_dim)
        x = self.encoder(x, input["length"])
        x, _ = self.attention(x)  # (batch_size, num_classes, hidden_dim)
        x = self.output(x)  # (batch_size, num_classes)
        return {"logits": x}


class BiGRULWAN(RNNLWAN):
    """BiGRU Labelwise Attention Network

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        num_classes (int): Total number of classes.
        rnn_dim (int): The size of bidirectional hidden layers. The hidden size of the GRU network
            is set to rnn_dim//2. Defaults to 512.
        rnn_layers (int): The number of recurrent layers. Defaults to 1.
        embed_dropout (float): The dropout rate of the word embedding. Defaults to 0.2.
        encoder_dropout (float): The dropout rate of the encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the encoder. Defaults to 0.
    """

    def __init__(
        self,
        embed_vecs,
        num_classes,
        rnn_dim=512,
        rnn_layers=1,
        embed_dropout=0.2,
        encoder_dropout=0,
        post_encoder_dropout=0,
    ):
        self.num_classes = num_classes
        self.rnn_dim = rnn_dim
        self.rnn_layers = rnn_layers
        super(BiGRULWAN, self).__init__(
            embed_vecs,
            num_classes,
            embed_dropout,
            encoder_dropout,
            post_encoder_dropout,
            rnn_dim,
        )

    def _get_encoder(self, input_size, encoder_dropout, post_encoder_dropout):
        assert self.rnn_dim % 2 == 0, """`rnn_dim` should be even."""
        return GRUEncoder(
            input_size,
            self.rnn_dim // 2,
            self.rnn_layers,
            encoder_dropout,
            post_encoder_dropout,
        )

    def _get_attention(self):
        return LabelwiseAttention(self.rnn_dim, self.num_classes)


class BiLSTMLWAN(RNNLWAN):
    """BiLSTM Labelwise Attention Network

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        num_classes (int): Total number of classes.
        rnn_dim (int): The size of bidirectional hidden layers. The hidden size of the LSTM network
            is set to rnn_dim//2. Defaults to 512.
        rnn_layers (int): The number of recurrent layers. Defaults to 1.
        embed_dropout (float): The dropout rate of the word embedding. Defaults to 0.2.
        encoder_dropout (float): The dropout rate of the encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the encoder. Defaults to 0.
    """

    def __init__(
        self,
        embed_vecs,
        num_classes,
        rnn_dim=512,
        rnn_layers=1,
        embed_dropout=0.2,
        encoder_dropout=0,
        post_encoder_dropout=0,
    ):
        self.num_classes = num_classes
        self.rnn_dim = rnn_dim
        self.rnn_layers = rnn_layers
        super(BiLSTMLWAN, self).__init__(
            embed_vecs,
            num_classes,
            embed_dropout,
            encoder_dropout,
            post_encoder_dropout,
            rnn_dim,
        )

    def _get_encoder(self, input_size, encoder_dropout, post_encoder_dropout):
        assert self.rnn_dim % 2 == 0, """`rnn_dim` should be even."""
        return LSTMEncoder(input_size, self.rnn_dim // 2, self.rnn_layers, encoder_dropout, post_encoder_dropout)

    def _get_attention(self):
        return LabelwiseAttention(self.rnn_dim, self.num_classes)


class BiLSTMLWMHAN(LabelwiseAttentionNetwork):
    """BiLSTM Labelwise Multihead Attention Network

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        num_classes (int): Total number of classes.
        rnn_dim (int): The size of bidirectional hidden layers. The hidden size of the LSTM network
            is set to rnn_dim//2. Defaults to 512.
        rnn_layers (int): The number of recurrent layers. Defaults to 1.
        embed_dropout (float): The dropout rate of the word embedding. Defaults to 0.2.
        encoder_dropout (float): The dropout rate of the encoder. Defaults to 0.
        post_encoder_dropout (float): The dropout rate of the dropout layer after the encoder. Defaults to 0.
        num_heads (int): The number of parallel attention heads. Defaults to 8.
        labelwise_attention_dropout (float): The dropout rate for the attention. Defaults to 0.
    """

    def __init__(
        self,
        embed_vecs,
        num_classes,
        rnn_dim=512,
        rnn_layers=1,
        embed_dropout=0.2,
        encoder_dropout=0,
        post_encoder_dropout=0,
        num_heads=8,
        labelwise_attention_dropout=0,
    ):
        self.num_classes = num_classes
        self.rnn_dim = rnn_dim
        self.rnn_layers = rnn_layers
        self.num_heads = num_heads
        self.labelwise_attention_dropout = labelwise_attention_dropout
        super(BiLSTMLWMHAN, self).__init__(
            embed_vecs,
            num_classes,
            embed_dropout,
            encoder_dropout,
            post_encoder_dropout,
            rnn_dim,
        )

    def _get_encoder(self, input_size, encoder_dropout, post_encoder_dropout):
        assert self.rnn_dim % 2 == 0, """`rnn_dim` should be even."""
        return LSTMEncoder(input_size, self.rnn_dim // 2, self.rnn_layers, encoder_dropout, post_encoder_dropout)

    def _get_attention(self):
        return LabelwiseMultiHeadAttention(
            self.rnn_dim, self.num_classes, self.num_heads, self.labelwise_attention_dropout
        )

    def forward(self, input):
        # (batch_size, sequence_length, embed_dim)
        x = self.embedding(input["text"])
        # (batch_size, sequence_length, hidden_dim)
        x = self.encoder(x, input["length"])
        # (batch_size, num_classes, hidden_dim)
        x, _ = self.attention(x, attention_mask=input["text"] == 0)
        x = self.output(x)  # (batch_size, num_classes)
        return {"logits": x}


class CNNLWAN(LabelwiseAttentionNetwork):
    """CNN Labelwise Attention Network

    Args:
        embed_vecs (torch.Tensor): The pre-trained word vectors of shape (vocab_size, embed_dim).
        num_classes (int): Total number of classes.
        filter_sizes (list): Size of convolutional filters.
        num_filter_per_size (int): The number of filters in convolutional layers in each size. Defaults to 50.
        embed_dropout (float): The dropout rate of the word embedding. Defaults to 0.2.
        post_encoder_dropout (float): The dropout rate of the encoder output. Defaults to 0.
        activation (str): Activation function to be used. Defaults to 'tanh'.
    """

    def __init__(
        self,
        embed_vecs,
        num_classes,
        filter_sizes=None,
        num_filter_per_size=50,
        embed_dropout=0.2,
        post_encoder_dropout=0,
        activation="tanh",
    ):
        self.num_classes = num_classes
        self.filter_sizes = filter_sizes
        self.num_filter_per_size = num_filter_per_size
        self.activation = activation
        self.hidden_dim = num_filter_per_size * len(filter_sizes)
        # encoder dropout is unused for CNN, we pass 0 to satisfy LabelwiseAttentionNetwork API
        super(CNNLWAN, self).__init__(embed_vecs, num_classes, embed_dropout, 0, post_encoder_dropout, self.hidden_dim)

    def _get_encoder(self, input_size, encoder_dropout, post_encoder_dropout):
        # encoder dropout is unused for CNN, we accept it to satisfy LabelwiseAttentionNetwork API
        return CNNEncoder(
            input_size,
            self.filter_sizes,
            self.num_filter_per_size,
            self.activation,
            post_encoder_dropout,
            channel_last=True,
        )

    def _get_attention(self):
        return LabelwiseAttention(self.hidden_dim, self.num_classes)

    def forward(self, input):
        # (batch_size, sequence_length, embed_dim)
        x = self.embedding(input["text"])
        x = self.encoder(x)  # (batch_size, sequence_length, hidden_dim)
        x, _ = self.attention(x)  # (batch_size, num_classes, hidden_dim)
        x = self.output(x)  # (batch_size, num_classes)
        return {"logits": x}


class AttentionXML_0(nn.Module):
    def __init__(
        self,
        embed_vecs,
        num_classes: int,
        rnn_dim: int,
        linear_size: list,
        freeze_embed_training: bool = False,
        rnn_layers: int = 1,
        embed_dropout: float = 0.2,
        encoder_dropout: float = 0,
        post_encoder_dropout: float = 0.5,
    ):
        super().__init__()
        self.embedding = Embedding(embed_vecs, freeze=freeze_embed_training, dropout=embed_dropout)
        self.encoder = LSTMEncoder(embed_vecs.shape[1], rnn_dim // 2, rnn_layers, encoder_dropout, post_encoder_dropout)
        self.attention = LabelwiseAttention(rnn_dim, num_classes)
        self.output = MultilayerLinearOutput([rnn_dim] + linear_size, 1)

    def forward(self, inputs):
        x = inputs["text"]
        # the index of padding is 0
        masks = x != 0
        lengths = masks.sum(dim=1)
        masks = masks[:, : lengths.max()]

        x = self.embedding(x)[:, : lengths.max()]  # batch_size, length, embedding_size
        x = self.encoder(x, lengths)  # batch_size, length, hidden_size
        x, _ = self.attention(x)  # batch_size, num_classes, hidden_size
        x = self.output(x)  # batch_size, num_classes
        return {"logits": x}


class AttentionXML_1(nn.Module):
    def __init__(
        self,
        embed_vecs,
        num_classes: int,
        rnn_dim: int,
        linear_size: list,
        freeze_embed_training: bool = False,
        rnn_layers: int = 1,
        embed_dropout: float = 0.2,
        encoder_dropout: float = 0,
        post_encoder_dropout: float = 0.5,
    ):
        super().__init__()
        self.embedding = Embedding(embed_vecs, freeze=freeze_embed_training, dropout=embed_dropout)
        self.encoder = LSTMEncoder(embed_vecs.shape[1], rnn_dim // 2, rnn_layers, encoder_dropout, post_encoder_dropout)
        self.attention = PartialLabelwiseAttention(rnn_dim, num_classes)
        self.output = MultilayerLinearOutput([rnn_dim] + linear_size, 1)

    def forward(self, inputs):
        x = inputs["text"]
        labels_selected = inputs["labels_selected"]
        # the index of padding is 0
        masks = x != 0
        lengths = masks.sum(dim=1)
        masks = masks[:, : lengths.max()]

        x = self.embedding(x)[:, : lengths.max()]  # batch_size, length, embedding_size
        x = self.encoder(x, lengths)  # batch_size, length, hidden_size
        x, _ = self.attention(x, labels_selected)  # batch_size, sample_size, hidden_size
        x = self.output(x)  # batch_size, sample_size
        return {"logits": x}
